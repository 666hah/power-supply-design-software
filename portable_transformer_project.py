"""Build a self-contained FEM input from the current design and a local CAD file.

No earlier extractor project, source ZIP or external tool installation is needed.
This module prepares and validates inputs only; CAD assembly/interference and the
field solution remain independent checks in the bundled extractor runtime.
"""
from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from calculation_scheduler import CalculationCancelled
from core_shape_catalog import get_core_shape
from field_core_cad import OUTLINE_TOLERANCE_MM, catalog_field_core
from transformer_geometry import (export_geometry_package, json_bytes, read_geometry_package,
                                  resolve_geometry)
from transformer_geometry_contract import profile_template
from transformer_sim_reference import _connections
from transformer_sim_runner import _sha, bind_solver_project
from transformer_simulation import _calculate


_MODES = {'assembled', 'half_center_gap', 'half_spacer'}


def automatic_field_inputs(config, environment):
    """Inspect design/machine selections without running an electrical or CAD solve."""
    from simulation_environment import core_name
    from transformer_preview_scene import nominal_winding_window, resolve_winding_placement

    env = deepcopy(environment or {})
    model = core_name(config)
    saved_model = env.get('core_model')
    pending_core = not model or model.casefold() in ('auto', '自动')
    if not pending_core:
        env['core_model'] = model
    winding = dict(config.get('winding_config') or {})
    profile = winding.get('model_3d') or {}
    bobbin = profile.get('bobbin') or {}
    physical = profile.get('core') or {}
    gap = physical.get('gap_geometry') or {}
    frame = profile.get('frame') or {}
    catalog = get_core_shape(model) or {}
    missing, notes = [], []
    if env.get('core_path') and saved_model and not pending_core and saved_model != model:
        missing.append('登记磁芯型号与计算磁芯不一致，请为当前磁芯重新选择实体。')
    explicit = str(env.get('core_path') or '')
    if not explicit and physical.get('geometry_reference'):
        reference = Path(physical['geometry_reference']).expanduser()
        if reference.is_absolute() and reference.suffix.lower() in ('.step', '.stp', '.brep'):
            explicit = env['core_path'] = str(reference)
            if not env.get('core_source'):
                env['core_source'] = '当前工程引用的磁芯实体；装配按当前设置校验。'
    generated = not explicit and bool(catalog_field_core(model))
    if generated:
        env.update(core_mode='assembled',
                   brep_unit='mm', translation_mm=[0., 0., 0.], rotation_deg=[0., 0., 0.],
                   gap_center_z_m=0., center_leg_radius_m=None)
        manufacturer, reference = catalog.get('manufacturer'), catalog.get('reference_model')
        detail = ' '.join(str(v) for v in (manufacturer, reference) if v)
        env['core_source'] = '由预览共用的三视图名义轮廓和当前气隙生成封闭参考实体'
        notes.append(f'名义 CAD 轮廓的离散简化误差上限为 {OUTLINE_TOLERANCE_MM:g} mm；绕组尺寸和气隙沿用当前设计。')
        if detail:
            env['core_source'] += '，规格参考 ' + detail
        if catalog.get('source_url'):
            env['core_source'] += '。' + catalog['source_url']
        cad_source = '规格书参考实体（自动生成）'
    elif explicit:
        cad_source = '已选择或登记的磁芯实体'
        if Path(explicit).suffix.lower() not in ('.step', '.stp', '.brep') or not Path(explicit).expanduser().is_file():
            missing.append('请选择存在的封闭实体 STEP/STP/BREP，STL 或预览网格不作为求解实体。')
        env.setdefault('core_mode', 'assembled')
        env.setdefault('brep_unit', 'mm')
        env.setdefault('translation_mm', [0., 0., 0.])
        env.setdefault('rotation_deg', [0., 0., 0.])
        env.setdefault('gap_center_z_m', (gap.get('center_xyz_m') or [0., 0., 0.])[2])
    elif pending_core:
        cad_source = '随当前计算自动选定磁芯后匹配'
    else:
        cad_source = '缺少求解实体'
        missing.append('这个磁芯暂无可自动生成的圆中柱实体，请在工具与模型中选择同型号 STEP/BREP。')

    # These datums are already in the design or in a registered CAD profile.
    # A catalog-derived coordinate uses the exact same mechanical datum as 3D
    # preview, and carries its reference status into the field input record.
    for key, source in (('r0_m', 'r0_m_if_circular'), ('z0_m', 'z0_m')):
        if env.get(key) is None and frame.get(source) is not None:
            env[key] = frame[source]
    if bobbin.get('winding_route_type') not in (None, 'circular'):
        missing.append('当前工程已有非圆形绕线路径。场解仅支持圆形等效匝，请核对绕组模型。')
    if generated or (explicit and saved_model == model and not any(env['translation_mm']) and not any(env['rotation_deg'])):
        winding, estimated = nominal_winding_window(winding, catalog)
        if estimated and winding.get('window_width') and winding.get('window_height'):
            notes.append('缺少的净窗口尺寸按规格图和骨架壁厚估算。')
        if (winding.get('window_width') and winding.get('window_height')
                and bobbin.get('winding_route_type') in (None, 'circular')
                and (env.get('r0_m') is None or env.get('z0_m') is None)):
            place = resolve_winding_placement(catalog, winding, profile, notes)
            if place['route_type'] == 'circular':
                if env.get('r0_m') is None:
                    env['r0_m'] = place['r0_mm'] * .001
                if env.get('z0_m') is None:
                    env['z0_m'] = place['z0_mm'] * .001
    if not pending_core:
        for key, label in (('window_width', '骨架净窗口宽度'), ('window_height', '骨架净窗口高度')):
            if not winding.get(key):
                missing.append('当前设计缺少' + label + '，请先在磁件页输入。')
        for key, source, label in (('r0_m', 'r0_m_if_circular', '线圈内侧基准半径r0'),
                                   ('z0_m', 'z0_m', '线圈轴向起点z0')):
            if env.get(key) is None:
                missing.append('当前工程缺少' + label + '，请按骨架/CAD坐标填写，不能自动猜测。')
                continue
            try:
                value = _number(env[key], label, positive=key == 'r0_m')
                if frame.get(source) is not None and not math.isclose(
                        value, _number(frame[source], label), rel_tol=1e-10, abs_tol=1e-12):
                    missing.append(label + '与当前工程不一致；请修改工程建模坐标或清空环境覆盖值。')
            except ValueError as exc:
                missing.append(str(exc))
    notes = [line.replace('仅作定位，不写回工程', '用于名义定位，采用前可复核')
                 .replace('预览暂用', '自动参考采用') for line in notes]
    summary = (f'{model or "自动磁芯"} · {cad_source}\n'
               '沿用工程层序、绝缘、绕组线束与逐匝位置；磁导率和气隙从设计读取。')
    if notes:
        summary += '\n' + '\n'.join(notes)
    return dict(ready=not missing, missing=missing, summary=summary, environment=env,
                cad_source=cad_source, generated_core=generated, winding=winding, assumptions=notes)


def _write_catalog_core(model, destination, gap_m, spacer, cancel):
    from transformer_sim_runner import _diagnostic, _field_process, _solver_command

    events = destination.parent / 'core-build-events.log'
    console = destination.parent / 'core-build-console.log'
    command = _solver_command('builtin', destination.parent)
    command += ['catalog-core', '--core-model', model, '--destination', str(destination), '--events', str(events),
                '--gap-mm', str(gap_m * 1000)]
    if spacer:
        command.append('--spacer')
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', 'VIRTUAL_ENV'):
        env.pop(key, None)
    env.update(POWER_DESIGN_FIELD_WORKDIR=str(destination.parent), PYINSTALLER_RESET_ENVIRONMENT='1')
    deadline = monotonic() + 90
    with console.open('wb') as log, _field_process(command, destination.parent, env, log) as poll:
        while (code := poll()) is None:
            if cancel():
                raise CalculationCancelled()
            if monotonic() > deadline:
                raise ValueError('规格轮廓生成实体超时，请选择已登记的同型号磁芯实体。')
            sleep(.12)
    if code or not destination.is_file():
        raise ValueError('规格轮廓生成磁芯实体失败。' + (_diagnostic(events) or _diagnostic(console)))


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + '需要有限数值')
    if positive and value <= 0:
        raise ValueError(label + '必须大于0')
    if nonnegative and value < 0:
        raise ValueError(label + '不能小于0')
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(label + '需要XYZ三个数值')
    return [_number(v, label) for v in value]


def _environment(value):
    """Validate local selections before doing any design calculation or copying."""
    if not isinstance(value, dict):
        raise ValueError('请先配置本机电磁仿真环境与磁芯模型')
    env = deepcopy(value)
    if env.get('core_mode') not in _MODES:
        raise ValueError('请选择磁芯装配方式：已装配实体、单半芯中柱磨隙或单半芯整体垫片')
    if env.get('brep_unit') not in ('mm', 'm'):
        raise ValueError('磁芯BREP单位需要mm或m；STEP按文件内声明单位读取')
    for key, label in (('core_path', '磁芯实体'), ('elmer_home', 'Elmer安装目录')):
        raw = env.get(key)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('请选择' + label)
        try:
            if key == 'elmer_home':
                from simulation_environment import normalize_elmer
                raw = normalize_elmer(raw)
            env[key] = str(Path(raw).expanduser().resolve(strict=True))
        except (OSError, ValueError):
            raise ValueError(label + '不存在，请在本机重新选择') from None
    core = Path(env['core_path'])
    if not core.is_file() or core.suffix.lower() not in ('.step', '.stp', '.brep'):
        raise ValueError('请选择封闭实体STEP/STP/BREP；图片或STL不能替代磁芯实体')
    if core.suffix.lower() in ('.step', '.stp'):
        with core.open('rb') as stream:
            header = stream.read(4096)
        if b'ISO-10303-21' not in header.upper():
            raise ValueError('磁芯文件不是可识别的STEP文本，请勿只修改文件后缀')
    home = Path(env['elmer_home'])
    if not home.is_dir() or not all((home / 'bin' / name).is_file()
            for name in ('ElmerSolver.exe', 'ElmerGrid.exe')):
        raise ValueError('Elmer目录须同时包含bin/ElmerSolver.exe及bin/ElmerGrid.exe')
    env['translation_mm'] = _vector(env.get('translation_mm'), '磁芯平移/mm')
    env['rotation_deg'] = _vector(env.get('rotation_deg'), '磁芯转角/°')
    env['gap_center_z_m'] = _number(env.get('gap_center_z_m'), '气隙中心Z/m')
    if env['core_mode'] != 'assembled' and abs(env['gap_center_z_m']) > 1e-10:
        raise ValueError('半芯模式要求拼合面和气隙中心Z=0、半芯位于Z<0；请先设置姿态')
    if env['core_mode'] == 'half_center_gap':
        env['center_leg_radius_m'] = _number(env.get('center_leg_radius_m'), '中柱半径/m', positive=True)
    elif env.get('center_leg_radius_m') is not None:
        env['center_leg_radius_m'] = _number(env['center_leg_radius_m'], '中柱半径/m', positive=True)
    if env.get('mesh_profile', 'standard') not in ('coarse', 'standard', 'fine'):
        raise ValueError('网格档位需要coarse、standard或fine')
    env['air_radius_m'] = _number(env.get('air_radius_m', .05), '空气域半径/m', positive=True)
    env['timeout_s'] = _number(env.get('timeout_s', 1200), '场求解超时/s', positive=True)
    if not isinstance(env.get('core_source'), str) or not env['core_source'].strip():
        raise ValueError('请填写磁芯模型/装配依据，或明确注明参考假设')
    return env


def _frame(profile, env):
    frame = profile.setdefault('frame', {})
    for key, name, label in (('r0_m_if_circular', 'r0_m', '线圈内侧基准半径r0'),
                             ('z0_m', 'z0_m', '线圈轴向起点z0')):
        existing, chosen = frame.get(key), env.get(name)
        if existing is not None:
            _number(existing, label, positive=name == 'r0_m')
            if chosen is not None and not math.isclose(
                    existing, _number(chosen, label, positive=name == 'r0_m'),
                    rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError(label + '与当前工程不一致；请修改当前建模坐标或清空环境覆盖值')
        elif chosen is None:
            raise ValueError('当前工程缺少' + label + '，请按骨架/CAD坐标填写，不能自动猜测')
        else:
            frame[key] = _number(chosen, label, positive=name == 'r0_m')


def _copy_verified(source, target, expected_sha, cancel):
    with source.open('rb') as reader, target.open('xb') as writer:
        for block in iter(lambda: reader.read(4 * 1024**2), b''):
            if cancel():
                raise CalculationCancelled()
            writer.write(block)
    if _sha(target, cancel) != expected_sha or _sha(source, cancel) != expected_sha:
        raise ValueError('磁芯文件在输入准备期间发生变化，请重新选择')


def prepare_portable_reference(config, *, environment, output_directory, cancelled=None):
    """Return ``{config, project_file, summary}`` without mutating the caller.

    The returned settings JSON uses relative source-ZIP and CAD paths, so its
    entire directory can be moved. Elmer remains a machine-local selection.
    Existing window, layer IDs, turn locations, connections and wire evidence
    are authoritative. Only fully blank connections may receive explicit
    series-additive reference assumptions.
    """
    cancel = cancelled or (lambda: False)
    if cancel():
        raise CalculationCancelled()
    candidate = deepcopy(config)
    from simulation_environment import core_name, load_environment
    if core_name(candidate).lower() in ('', 'auto', '自动'):
        from joint_simulation import _freeze_hardware
        baseline = _calculate(candidate, cancel)
        candidate = _freeze_hardware(candidate, baseline)
        if not (environment or {}).get('core_path'):
            registered = load_environment(candidate)
            environment = dict(registered, **{k: v for k, v in (environment or {}).items()
                if k not in ('core_model', 'core_path', 'core_mode', 'core_source', 'center_leg_radius_m', 'r0_m', 'z0_m')
                and v is not None and v != ''})
        if core_name(candidate).lower() in ('', 'auto', '自动'):
            raise ValueError('自动选择的磁芯未能冻结，请在磁件页明确指定磁芯')
    automatic = automatic_field_inputs(candidate, environment)
    if not automatic['ready']:
        raise ValueError('\n'.join(automatic['missing']))
    winding = candidate['winding_config'] = automatic['winding']
    raw_environment = automatic['environment']
    directory = Path(output_directory).expanduser().resolve() / ('自动电磁输入-' + uuid4().hex[:10])
    generated = automatic['generated_core']
    env = raw_environment if generated else _environment(raw_environment)
    for key, label in (('window_width', '骨架净窗口宽度'), ('window_height', '骨架净窗口高度')):
        if not winding.get(key):
            raise ValueError('当前设计缺少' + label + '，请先在磁件页输入；仅凭磁芯STEP不能推定骨架净窗口')
        _number(winding[key], label, positive=True)
    profile = deepcopy(winding.get('model_3d') or profile_template())
    winding['model_3d'] = profile
    _frame(profile, env)
    bobbin = profile.setdefault('bobbin', {})
    if bobbin.get('winding_route_type') not in (None, 'circular'):
        raise ValueError('内置提取首版支持圆形等效匝；不能将已有非圆形路径静默改成圆形')
    if not bobbin.get('winding_route_type') or bobbin.get('status') in (None, 'unconfirmed'):
        bobbin.update(winding_route_type='circular', status='assumed',
                      source=bobbin.get('source') or '沿用当前设计或同型号机械基准的圆形等效匝')
    core = profile.setdefault('core', {})
    run = _calculate(candidate, cancel)
    geometry, _ = resolve_geometry(run.runtime_bundle()['cases'], '0' * 64, '0' * 64,
                                   'T1', profile, cancelled=cancel)
    if not geometry['ready']['cross_section'] or not geometry['checks']['two_dimensional_fit']:
        raise ValueError('当前线材、层序、手动匝位置与净窗口未通过可绕制评估，请先调整磁件设计')
    connection_note = _connections(profile, geometry)
    # Re-resolve: partial, tapped or parallel connections must not be silently
    # replaced by a simple series circuit just because some fields exist.
    geometry, _ = resolve_geometry(run.runtime_bundle()['cases'], '0' * 64, '0' * 64,
                                   'T1', profile, cancelled=cancel)
    if (geometry['connection_matrix']['values'] is None or
            any(p['turns_match_calculator'] is not True for p in geometry['connections'])):
        raise ValueError('当前绕组接线不完整或含未支持的外接抽头/并联约束，请在建模设置中补全')
    target = geometry['design_targets'].get('air_gap') or {}
    physical = core.get('gap_geometry') or {}
    gap = physical.get('length_m', target.get('gap_m'))
    gap = _number(gap, '当前设计总气隙/m', nonnegative=True)
    mu = _number(target.get('mu_r'), '当前设计相对磁导率', positive=True)
    if mu < 1:
        raise ValueError('当前线性铁氧体磁导率不能小于1')
    expected_type = {'half_center_gap': 'center_leg_ground', 'half_spacer': 'spacer'}.get(env['core_mode'])
    if gap and expected_type and physical.get('type') not in (None, expected_type):
        raise ValueError('所选半芯气隙加工方式与当前设计指定方式不符')
    if physical.get('center_xyz_m') is not None:
        center = physical['center_xyz_m']
        if (not math.isclose(center[0], 0., abs_tol=1e-12) or
                not math.isclose(center[1], 0., abs_tol=1e-12) or
                not math.isclose(center[2], env['gap_center_z_m'], rel_tol=1e-10, abs_tol=1e-12)):
            raise ValueError('所选气隙中心与当前工程指定的气隙位置不符')
    if generated:
        # Validate machine paths before asking OCC to build the reference solid.
        from simulation_environment import normalize_elmer
        root = Path(normalize_elmer(env.get('elmer_home')) or '.')
        if not all((root / 'bin' / name).is_file() for name in ('ElmerSolver.exe', 'ElmerGrid.exe')):
            raise ValueError('请选择含 ElmerSolver.exe 和 ElmerGrid.exe 的 Elmer 安装目录')
        (directory / 'models').mkdir(parents=True, exist_ok=False)
        nominal = directory / 'models/core.brep'
        _write_catalog_core(env['core_model'], nominal, gap, physical.get('type') == 'spacer', cancel)
        env = _environment(dict(env, core_path=str(nominal)))
    source = Path(env['core_path'])
    source_sha = _sha(source, cancel)
    if core.get('geometry_sha256') and core['geometry_sha256'].lower() != source_sha:
        raise ValueError('所选磁芯实体与当前工程已冻结CAD的SHA-256不符，请先复核并更新工程模型')
    material_source = target.get('material_source') or '当前电源设计指定的线性相对磁导率，非偏磁测量'
    assumptions = list(profile.get('assumptions') or []) + automatic['assumptions']
    if connection_note != '保留当前工程接线':
        assumptions.append(connection_note)
    if not physical:
        physical = dict(type='none' if gap == 0 else expected_type or 'center_leg_ground',
                        length_m=gap, center_xyz_m=[0., 0., env['gap_center_z_m']],
                        source=('按本设计估算气隙构造的名义中柱磨隙，待实体检查与实测校核'
                                if generated else '当前电源磁路初算的等效总气隙；已装配CAD须在实体检查中独立核对，未按目标电感拟合'))
        core['gap_geometry'] = physical
        assumptions.append(physical['source'])
    # Preserve intentional winding placement. Only the selected local CAD
    # reference and missing model provenance are added to the exported copy.
    local_cad = 'models/core' + source.suffix.lower()
    core.update(geometry_reference=local_cad, geometry_sha256=source_sha)
    if not core.get('material_reference'):
        core['material_reference'] = material_source
    assumptions.extend(['选定CAD仅通过文件与哈希检查；半芯姿态、实体气隙、空气域及线圈干涉由后续CAD检查独立判定。',
                        '采用均匀电流的圆形闭合等效匝；未包含螺旋跨层线、引线、涡流和非线性偏磁。'])
    profile['assumptions'] = list(dict.fromkeys(assumptions))
    if not generated:
        (directory / 'models').mkdir(parents=True, exist_ok=False)
        _copy_verified(source, directory / local_cad, source_sha, cancel)
    package = directory / '当前绕制输入.zip'
    export_geometry_package(_calculate(candidate, cancel), package, candidate, cancelled=cancel)
    final_geometry = read_geometry_package(package)
    project = dict(schema='transformer-coupling-tool.project.v1', name='T1',
        package_path=package.name, package_sha256=_sha(package, cancel), primary_port='P',
        core=dict(path=local_cad, sha256=source_sha, calculator_core_model=final_geometry['core']['calculator_core'],
                  mode=env['core_mode'], brep_unit=env['brep_unit'], translation_mm=env['translation_mm'],
                  rotation_deg=env['rotation_deg'], total_gap_m=gap,
                  center_leg_radius_m=env.get('center_leg_radius_m'), gap_center_z_m=env['gap_center_z_m'],
                  source=env['core_source'].strip()),
        frame=dict(r0_m=profile['frame']['r0_m_if_circular'], z0_m=profile['frame']['z0_m']),
        material=dict(name=final_geometry['core']['calculator_material'], relative_permeability=mu,
                      temperature_C=25., source=material_source, frequency_Hz=0., bias_current_A=0.),
        connections=deepcopy(profile), classification='reference_assumptions',
        assumptions=profile['assumptions'],
        solver=dict(elmer_home=env['elmer_home'], mesh_profile=env.get('mesh_profile', 'standard'),
                    air_radius_m=env['air_radius_m'], timeout_s=env['timeout_s']), output_root='.')
    path = directory / '自动提取设置.json'
    path.write_bytes(json_bytes(project))
    # Use the same contract as manual/legacy projects. This does not call CAD,
    # mesh or Elmer and must not be described as field-solution validation.
    bind_solver_project(package, path, directory)
    summary = (f"已从当前设计生成可迁移输入：{project['core']['calculator_core_model']} · "
               f"{project['material']['name']} · μr={mu:g}\n"
               f"净窗口 {winding['window_width']*1e3:g}×{winding['window_height']*1e3:g} mm；"
               f"r0={project['frame']['r0_m']*1e3:g} mm，z0={project['frame']['z0_m']*1e3:g} mm\n"
               f"总气隙 {gap*1e3:g} mm；{connection_note}\n"
               'CAD与绕制包已复制到同一输入目录；后续仍须通过实体装配/干涉检查和场求解。')
    return dict(config=candidate, project_file=str(path), summary=summary)
