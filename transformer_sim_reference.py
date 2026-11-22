"""Prepare a reviewable local extraction profile from an existing core project."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import math

from transformer_geometry import (export_geometry_package, json_bytes, read_geometry_package,
                                  resolve_geometry, strict_json)
from transformer_geometry_contract import profile_template, validate_profile
from transformer_sim_runner import bind_solver_project
from transformer_simulation import _calculate, _sha
from winding_layout import assess_winding_window, transformer_windings


NOMINAL_CONNECTION_SOURCE = '名义绕制假设：从 +Z 观察各段逆时针，电流流入起点同名端，同一绕组各段按层序串联相加，中间节点不外接。'
PUBLIC_CONNECTION_SOURCE = '公开演示算例的合成骨架和接线假设'


def _has_wiring(profile):
    return (profile.get('terminals') or profile.get('leads') or
            any(any(s.get(key) for key in ('start_node', 'end_node', 'dot_node', 'direction'))
                for s in profile.get('sections', {}).values()) or
            any(any(p.get(key) for key in ('section_order', 'connection', 'dot_node', 'other_node'))
                for p in profile.get('ports', {}).values()))


def _nominal_wiring(groups, source):
    sections, ports, terminals = {}, {}, []
    for label, segments in groups.items():
        ids = [sid for sid, _ in segments]
        if source == PUBLIC_CONNECTION_SOURCE:
            nodes = [f'{label}_N{i}' for i in range(len(ids) + 1)]
        else:
            nodes = [label + '_D'] + [f'{label}_J{i}' for i in range(1, len(ids))] + [label + '_R']
        for i, (sid, count) in enumerate(segments):
            sections[sid] = dict(winding_id=label, turns=count, start_node=nodes[i], end_node=nodes[i+1],
                                 dot_node=nodes[i], direction='ccw', status='assumed', source=source)
        ports[label] = dict(dot_node=nodes[0], other_node=nodes[-1], connection='series',
                            section_order=ids, status='assumed', source=source)
        for n in nodes[1:-1]:
            terminals.append(dict(node=n, pin='REF_' + n, position_xyz_m=None, external_connection='none',
                                  net=None, status='assumed', source=source))
    return dict(sections=sections, ports=ports, terminals=terminals)


def _automatic_wiring_source(profile):
    """Recognize complete producer patterns. An assumed custom wire is still explicit."""
    sections, ports = profile.get('sections', {}), profile.get('ports', {})
    if not sections or not ports or profile.get('leads'):
        return None
    source = next(iter(sections.values())).get('source')
    if source not in (NOMINAL_CONNECTION_SOURCE, PUBLIC_CONNECTION_SOURCE):
        return None
    groups = {}
    for winding, port in ports.items():
        order = port.get('section_order', [])
        if not order or len(order) != len(set(order)) or any(sid not in sections for sid in order):
            return None
        groups[winding] = [(sid, sections[sid]['turns']) for sid in order]
    expected = _nominal_wiring(groups, source)
    if expected['sections'] != sections or expected['ports'] != ports:
        return None
    terminals = {t['node']: t for t in profile.get('terminals', [])}
    if terminals == {t['node']: t for t in expected['terminals']} or (
            source == PUBLIC_CONNECTION_SOURCE and not terminals):
        return source
    return None


def synchronize_simulation_connections(profile, cases):
    """Synchronize the run's private profile from the current physical layers."""
    validate_profile(profile)
    if not cases or not cases[0].get('result'):
        return None
    case = cases[0]
    assessment = assess_winding_window(transformer_windings(case['result']), case['p'].get('winding_config'))
    layers = assessment.get('physical_layers')
    if not layers or not assessment['fits']:
        return None  # The geometry resolver reports missing windows, overflow, and limits.
    groups = {}
    layer_by_id = {layer['section_id']: layer for layer in layers}
    for layer in layers:
        groups.setdefault(layer['winding_id'], []).append((layer['section_id'], layer['turns']))

    source = _automatic_wiring_source(profile)
    if source:
        refreshed = _nominal_wiring(groups, source)
        # Terminal list order carries no wiring information.
        if ({t['node']: t for t in profile.get('terminals', [])} ==
                {t['node']: t for t in refreshed['terminals']}):
            refreshed['terminals'] = profile.get('terminals', [])
        if any(profile.get(key, []) != value for key, value in refreshed.items()):
            before = profile['ports']
            after = refreshed['ports']
            order_changed = ({key: p['section_order'] for key, p in before.items()} !=
                             {key: p['section_order'] for key, p in after.items()})
            profile.update(refreshed)
            return ('已按当前层序重建软件生成的串联接线。' if order_changed else
                    '已自动同步当前层匝数和段接线。')
        return None
    if not _has_wiring(profile):
        profile.update(_nominal_wiring(groups, NOMINAL_CONNECTION_SOURCE))
        return NOMINAL_CONNECTION_SOURCE

    updated = []
    for sid, section in profile.get('sections', {}).items():
        layer = layer_by_id.get(sid)
        if layer and section['winding_id'] == layer['winding_id'] and section['turns'] != layer['turns']:
            section['turns'] = layer['turns']
            updated.append(sid)
    if updated:
        return '已自动同步现有段的匝数，沿用节点和绕向。更新层：' + '、'.join(updated)
    return None


def _connections(profile, geometry):
    if geometry['connection_matrix']['values'] is not None:
        return '保留当前工程接线'
    if _has_wiring(profile):
        raise ValueError('当前接线已部分填写或有外接抽头/并联约束，请在三维建模设置中核对该绕组。')
    turns = {s['section_id']: s['turns'] for s in geometry['physical_sections']}
    groups = {w['id']: [(sid, turns[sid]) for sid in w['section_ids']] for w in geometry['windings']}
    profile.update(_nominal_wiring(groups, NOMINAL_CONNECTION_SOURCE))
    return NOMINAL_CONNECTION_SOURCE


def prepare_reference(config, *, project_file, output_directory, cancelled=None):
    template = Path(project_file).resolve(strict=True)
    settings = strict_json(template.read_bytes())
    if settings.get('schema') != 'transformer-coupling-tool.project.v1':
        raise ValueError('请选择磁芯参考工程的提取设置 JSON')
    reference_zip = (template.parent / settings['package_path']).resolve(strict=True)
    if _sha(reference_zip) != settings['package_sha256']:
        raise ValueError('磁芯参考工程的原几何包与模板哈希不同')
    reference = read_geometry_package(reference_zip)
    candidate = deepcopy(config)
    winding = candidate.setdefault('winding_config', {})
    profile = winding.get('model_3d') or profile_template()
    winding['model_3d'] = profile
    for key, dimension in [('window_width', 'axial_window_m'), ('window_height', 'radial_window_m')]:
        if not winding.get(key):
            value = reference['bobbin'].get(dimension)
            if not value or value <= 0:
                raise ValueError('同型号参考工程没有净窗口尺寸，请在当前磁件页输入窗口宽和高')
            winding[key] = value
    bobbin = profile.setdefault('bobbin', {})
    if bobbin.get('winding_route_type') not in (None, 'circular'):
        raise ValueError('当前提取工具只支持圆形匝路径，已有轨迹需由设计者核对')
    if not bobbin.get('winding_route_type') and reference['bobbin'].get('winding_route_type') not in ('circular', None):
        raise ValueError('模板骨架并非圆形匝路径')
    frame = profile.setdefault('frame', {})
    for key, ref in [('r0_m_if_circular', 'r0_m'), ('z0_m', 'z0_m')]:
        if frame.get(key) is None:
            frame[key] = settings['frame'][ref]
        if frame[key] is None:
            raise ValueError('参考工具设置中缺少骨架基准 ' + ref)
    if not bobbin.get('winding_route_type') or bobbin.get('status') in (None, 'unconfirmed'):
        bobbin.update(winding_route_type='circular', status='assumed', source='同型号参考工程名义骨架：' + template.name)
    # Resolve the current windings, including current wire count and every user-positioned turn.
    first = _calculate(candidate, cancelled)
    cases = first.runtime_bundle()['cases']
    connection_update = synchronize_simulation_connections(profile, cases)
    g, _ = resolve_geometry(cases, '0'*64, '0'*64, 'T1', profile, cancelled=cancelled)
    if (g['core']['calculator_core'] != reference['core']['calculator_core'] or
            settings['core'].get('calculator_core_model', g['core']['calculator_core']) != g['core']['calculator_core']):
        raise ValueError('当前计算的磁芯型号与参考工程不同，请选择同型号磁芯')
    if not g['ready']['cross_section'] or not g['checks']['two_dimensional_fit']:
        raise ValueError('当前线材、层序与净窗口未通过可绕制评估，请先调整磁件设计')
    note = _connections(profile, g)
    if any(p['turns_match_calculator'] is False for p in g['connections']):
        raise ValueError('当前层匝数与接线极性归算的有效匝数不符，请核对绕向和同名端。')
    if connection_update:
        note = connection_update
        profile['assumptions'] = list(dict.fromkeys([*(profile.get('assumptions') or []), note]))
    target = g['design_targets']['air_gap']
    core = settings['core']
    physical = (profile.get('core') or {}).get('gap_geometry') or {}
    gap = physical.get('length_m', target.get('gap_m'))
    if gap is None or target['mu_r'] is None:
        raise ValueError('需要当前磁件的磁导率和可用的气隙设计')
    if core['mode'] == 'assembled' and not math.isclose(core['total_gap_m'], gap, abs_tol=1e-11):
        raise ValueError('参考 STEP 为已装配实体，现有气隙与本设计不同。请选择可磨隙的半芯或相符的装配模型')
    core.update(path=str((template.parent / core['path']).resolve(strict=True)), total_gap_m=gap,
                calculator_core_model=g['core']['calculator_core'],
                source=physical.get('source') or '参考模板磁芯实体，按当前电源磁路初算的等效总气隙进行名义装配。')
    material = settings['material']
    material.pop('source_file', None)
    material.update(name=g['core']['calculator_material'], relative_permeability=target['mu_r'],
                    source=target.get('material_source') if target.get('mu_r_source') != '用户指定相对磁导率' and target.get('material_source')
                    else '采用当前电源设计的相对磁导率；按零偏置常数建模。')
    settings.update(frame=dict(z0_m=frame['z0_m'], r0_m=frame['r0_m_if_circular']),
                    connections=profile, classification='reference_assumptions', assumptions=[note, core['source']])
    if settings['solver'].get('elmer_home'):
        settings['solver']['elmer_home'] = str((template.parent / settings['solver']['elmer_home']).resolve())
    directory = Path(output_directory).resolve() / ('参考提取设置-' + uuid4().hex[:10])
    directory.mkdir(parents=True, exist_ok=False)
    package = directory / '参考绕制输入.zip'
    export_geometry_package(_calculate(candidate, cancelled), package, candidate, cancelled=cancelled)
    settings.update(package_path=package.name, package_sha256=_sha(package), output_root='.')
    new_path = directory / '提取设置.json'
    new_path.write_bytes(json_bytes(settings))
    bind_solver_project(package, new_path, directory)
    layers = ' → '.join(s['winding_id'] + ' ' + str(s['turns']) + ' 匝' for s in g['physical_sections'])
    summary = (f"{g['core']['calculator_core']} · {material['name']} · μr={target['mu_r']:g}\n"
               f"净窗口 {winding['window_width']*1e3:.3g} × {winding['window_height']*1e3:.3g} mm，"
               f"r0={frame['r0_m_if_circular']*1e3:g} mm，z0={frame['z0_m']*1e3:g} mm。\n"
               f"层序：{layers}\n总气隙 {gap*1e3:.6g} mm；{core['source']}\n{note}")
    return dict(config=candidate, project_file=str(new_path), summary=summary,
                connection_update=connection_update)
