"""One Word report from frozen field, calculator and actual SPICE evidence.

This renderer never starts a solver or recalculates a design. The independent
engines own the values; one python-docx Document owns sections, equations and
image relationships throughout the report.
"""
import base64
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlparse
from zipfile import ZipFile


def _number(value, scale=1, suffix=''):
    if value is None:
        return '未取得'
    if isinstance(value, str):
        return value
    try:
        value = float(value) * scale
    except (ValueError, TypeError):
        return str(value)
    return f'{value:.6g}{suffix}' if math.isfinite(value) else '无有效值'


class _Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img' and attrs.get('src'):
            self.items.append((attrs['src'], attrs.get('alt') or '变压器场仿真图'))


def _field_images(report_path):
    """Read local / embedded raster figures; never fetch remote content."""
    from PIL import Image
    if not report_path or not Path(report_path).is_file():
        return [], ['原始场报告图像文件不可用，本节仅保留已取得的矩阵与条件。']
    report = Path(report_path).resolve()
    parser = _Images()
    if report.stat().st_size > 64 * 1024 * 1024:
        return [], ['原始场报告超过64 MiB，未载入图像；完整文件保留在工程目录。']
    parser.feed(report.read_text('utf-8-sig'))
    images, notes, seen = [], [], set()
    for source, caption in parser.items:
        if source in seen:
            continue
        seen.add(source)
        try:
            if source.startswith('data:image/'):
                header, body = source.split(',', 1)
                if ';base64' not in header:
                    raise ValueError('图像并非base64编码')
                blob = base64.b64decode(body, validate=True)
            else:
                parsed = urlparse(source)
                if parsed.scheme or parsed.netloc:
                    raise ValueError('不自动下载远程图像')
                path = (report.parent / unquote(parsed.path)).resolve()
                if not path.is_relative_to(report.parent) or not path.is_file():
                    raise ValueError('图像未包含在本地场报告目录中')
                blob = path.read_bytes()
            if len(blob) > 20 * 1024 * 1024:
                raise ValueError('单张图像超过20 MiB')
            with Image.open(BytesIO(blob)) as image:
                image.verify()
            images.append((blob, caption))
        except (ValueError, OSError) as exc:
            notes.append(f'{caption}：未嵌入，{exc}')
    return images, notes


def _evidence(record, spice_result):
    circuit = record.get('circuit') or {}
    if isinstance(circuit.get('evidence'), dict):
        return circuit['evidence']
    if circuit.get('evidence_path') and Path(circuit['evidence_path']).is_file():
        return json.loads(Path(circuit['evidence_path']).read_text('utf-8-sig'))
    result = spice_result or circuit.get('summary') or {}
    if result.get('path') and Path(result['path']).is_file():
        with ZipFile(result['path']) as archive:
            if 'comparison.json' in archive.namelist():
                return json.loads(archive.read('comparison.json'))
    return None


def _archived_design_bundle(record, archive_directory):
    """Reopen the frozen calculation owned by this joint run."""
    calculation = record.get('calculation') or {}
    if not calculation:
        return None, None
    snapshot_path = calculation.get('snapshot_path')
    snapshot_id = calculation.get('snapshot_id')
    if not isinstance(snapshot_path, str) or not snapshot_path or not snapshot_id:
        return None, '运行记录缺少计算快照文件或编号。'
    adopted = record.get('adopted_config')
    if not isinstance(adopted, dict):
        return None, '运行记录缺少已采用的设计参数，无法校对计算快照。'

    recorded_directory = Path(record['directory']) if record.get('directory') else None
    directory = Path(archive_directory) if archive_directory is not None else recorded_directory
    if directory is None:
        return None, '运行记录缺少计算快照所在目录。'
    declared = Path(snapshot_path)
    if declared.parent not in (Path('.'), recorded_directory, directory):
        return None, '计算快照路径超出联合运行目录。'
    from design_engine.service import read_snapshot, restore_report_bundle, validate_spec
    from engineering_acceptance import input_fingerprint
    try:
        directory = directory.resolve()
        snapshot = (directory / declared.name).resolve()
        if not snapshot.is_relative_to(directory):
            return None, '计算快照路径超出联合运行目录。'
        if not snapshot.is_file():
            return None, '联合运行目录缺少计算快照文件。'
        payload = read_snapshot(snapshot)
        if payload['snapshot_id'] != snapshot_id:
            return None, '计算快照编号与本次运行记录不一致。'
        spec = payload.get('spec')
        if not isinstance(spec, dict):
            return None, '计算快照缺少本次采用的设计参数。'
        fingerprint = input_fingerprint(spec)
        if fingerprint != input_fingerprint(adopted):
            # An older joint record can store display units or omit fields that
            # the calculation entry normalizes before freezing the snapshot.
            normalized = validate_spec(adopted)
            if not normalized['ok'] or fingerprint != input_fingerprint(normalized['spec']):
                return None, '计算快照与本次采用的设计参数不一致。'
        return restore_report_bundle(payload), None
    except (OSError, RuntimeError):
        return None, '计算快照文件无法读取。'
    except json.JSONDecodeError:
        return None, '计算快照 JSON 格式损坏。'
    except ValueError as exc:
        return None, f'计算快照校验失败。{exc}'


_STEP_NAMES = {'prepare': '准备输入', 'field': '变压器场解', 'margin': '矩阵与漏感裕量',
               'calculation': '采用参数复算', 'spice': '电路仿真', 'report': '报告汇总'}
_STEP_STATES = {'complete': '完成', 'completed': '完成', 'partial': '需复核',
                'failed': '失败', 'error': '失败', 'cancelled': '已取消',
                'skipped': '未执行', 'pending': '待执行', 'running': '执行中'}


def _stage_name(stage, record):
    name = stage.get('name', '')
    if name == 'field' and record.get('resumed_field'):
        return '既有场解复核'
    return _STEP_NAMES.get(name) or stage.get('label') or name


def _input_label(spec):
    if not spec:
        return '输入待补'
    lo = spec.get('V_in_min', spec.get('V_in'))
    hi = spec.get('V_in_max', spec.get('V_in'))
    if lo is None or hi is None:
        return '输入待补'
    return f'固定输入 {_number(lo)} V' if lo == hi else f'输入 {_number(lo)} 至 {_number(hi)} V'


def _voltage_observations(evidence):
    from engineering_acceptance import _simulation_values
    cases = [case for case in (evidence or {}).get('cases', []) if not case.get('fault_test')]
    return [(case, _simulation_values(case)) for case in cases]


def _joint_review(record, design_spec, bundle, evidence, snapshot_issue):
    from report_architecture import acceptance_columns, acceptance_findings, acceptance_snapshot

    stages = record.get('stages') or []
    errors = list(map(str, record.get('errors') or []))
    if record.get('error'):
        errors.append(str(record['error']))
    complete_states = ('complete', 'completed', 'success')
    workflow_incomplete = bool(errors or record.get('status') not in complete_states
                               or any(s.get('status') not in complete_states for s in stages))
    acceptance = None
    exceeded = []
    findings = [('设计计算快照', snapshot_issue)] if snapshot_issue else []
    if design_spec is not None:
        acceptance = acceptance_snapshot(design_spec, bundle, joint_record=record, spice_evidence=evidence)
        labels, _ = acceptance_columns(acceptance, bundle, design_spec)
        exceeded = acceptance_findings(acceptance, labels)
        if acceptance.get('simulation_matched'):
            from engineering_acceptance import _number as _evidence_number
            parts = (design_spec.get('component_management') or {}).get('items') or {}
            rating = _evidence_number((parts.get('Q1') or {}).get('voltage_V'))
            observations = _voltage_observations(evidence)
            for case, obs in observations:
                peak = obs.get('startup_vds_peak')
                if rating is not None and rating > 0 and peak is not None and peak > rating:
                    context = f"{case.get('id', '')} " if len(observations) > 1 else ''
                    findings.insert(0, ('启动 MOS Vds 超额定',
                                        f'{context}{_number(peak)} V，Q1 额定 {_number(rating)} V。'))
    simulation = {}
    if evidence is not None:
        from spice_comparison_report import simulation_summary
        simulation = simulation_summary(evidence)
        findings.extend(simulation.get('findings') or [])
    summary = (acceptance or {}).get('summary') or {}
    state = summary.get('state', 'undefined')
    workflow = '联合流程需复核' if workflow_incomplete else '联合流程已完成'
    verdict = '工程验收 ' + (summary.get('label') or '待补设计输入')
    stage_errors = {_stage_name(s, record): str(s['error']) for s in stages if s.get('error')}
    unique_errors = [error for error in dict.fromkeys(errors) if error not in stage_errors.values()]
    review_rows = [(name, error) for name, error in stage_errors.items() if error != '前置阶段未完成']
    review_rows.extend(('流程', error) for error in unique_errors)
    review_rows.extend(findings)
    review_rows = list(dict.fromkeys(review_rows))
    missing_rows = sum(any(cell.get('status') in ('undefined', 'stale')
                           for cell in row.get('cases', {}).values())
                       for row in (acceptance or {}).get('rows', []))
    return dict(acceptance=acceptance, simulation=simulation, state=state, workflow=workflow, verdict=verdict,
                workflow_incomplete=workflow_incomplete, pending=missing_rows,
                exceeded=exceeded, review_rows=review_rows, unique_errors=unique_errors)


def _key_results(doc, field, margin, metrics, voltage_observations):
    from docx_layout import table
    rows = []
    for key, name in (('primary_self_H', '场解原边开路自感 / µH'),
                      ('primary_short_H', '场解原边短路电感 / µH')):
        if field.get(key) is not None:
            rows.append((name, _number(field[key], 1e6)))
    if margin.get('adopted_primary_short_H') is not None:
        rows.append(('采用原边短路电感 / µH', _number(margin['adopted_primary_short_H'], 1e6)))
    if metrics:
        # An archived result already carries the metrics. Report them directly
        # rather than reconstructing a simulation or current-design calculation.
        for key, name, scale in (
            ('frequency_Hz', '计算开关频率 / kHz', 1e-3),
            ('efficiency', '计算效率 / %', 100),
        ):
            values = [_number(case.get(key), scale) for case in metrics]
            rows.append((name, values[0] if len(values) == 1 else
                         ' / '.join(f"{c.get('case', '')} {v}" for c, v in zip(metrics, values))))
    for key, name in (('vds_peak', '仿真稳态 MOS Vds 峰值 / V'),
                      ('startup_vds_peak', '仿真全启动 MOS Vds 峰值 / V')):
        values = [(case, obs[key]) for case, obs in voltage_observations if obs.get(key) is not None]
        if values:
            case, peak = max(values, key=lambda pair: pair[1])
            value = _number(peak)
            if len(voltage_observations) > 1:
                value += f" ({case.get('id', '')})"
            rows.append((name, value))
    if rows:
        table(doc, ['关键指标', '本次值'], rows, [3.6, 3.5])


def _matrices(doc, field, margin):
    """Combine original and adopted values only when their port order matches."""
    from docx_layout import paragraph, table
    from report_architecture import module_section
    ports = field.get('port_order') or []
    adopted_ports = margin.get('port_order') or ports

    def valid(matrix, labels):
        return bool(labels) and len(matrix) == len(labels) and all(
            isinstance(row, (list, tuple)) and len(row) == len(labels) for row in matrix)

    def add(labels, rows, title):
        module_section(doc, title, level=2, new_page=False)
        table(doc, ['端口'] + labels, [[label] + row for label, row in zip(labels, rows)],
              [.7] + [6.4 / len(labels)] * len(labels))

    for key, title, scale in (('L_ports_H', '自感与互感矩阵 µH', 1e6),
                              ('k_ports', '有符号耦合系数矩阵', 1)):
        original = field.get(key) or []
        adopted = margin.get('adopted_' + key) or []
        original_ok, adopted_ok = valid(original, ports), valid(adopted, adopted_ports)
        if original_ok and adopted_ok and list(ports) == list(adopted_ports):
            changed = original != adopted
            add(list(ports), [[_number(before, scale) if before == after else
                               f'{_number(before, scale)} → {_number(after, scale)}'
                               for before, after in zip(a, b)] for a, b in zip(original, adopted)],
                title + (' 场解 → 采用' if changed else ' 场解与采用相同'))
        else:
            if original_ok:
                add(list(ports), [[_number(value, scale) for value in row] for row in original], '场解' + title)
            elif field:
                paragraph(doc, '场解' + title + '待补。', True)
            if adopted_ok:
                add(list(adopted_ports), [[_number(value, scale) for value in row] for row in adopted], '采用' + title)
            elif margin:
                paragraph(doc, '采用' + title + '待补。', True)


def write_joint_report(path, record, *, design_run=None, spice_result=None, archive_directory=None):
    """Consume the joint workflow record and optional in-memory design run.

    ``record.field`` is the verified transformer comparison record. ``margin``
    keeps both matrix versions, achieved leakage and the engineering factor.
    An archived run uses its verified saved calculation. ``archive_directory``
    locates the snapshot after the joint run folder is moved. Partial and
    failed stages produce a useful report with explicit gaps.
    Returns a rendering receipt; the caller owns cancellation / publication.
    """
    from docx_layout import equation, figure, finalize_book_report, new_document, paragraph, table
    from report_architecture import (acceptance_group_line, add_acceptance_report,
                                     conclusion_line, missing_evidence_note, module_section)
    from transformer_sim_report import distinct_endpoint_metrics
    if design_run is not None:
        bundle, snapshot_issue = design_run.runtime_bundle(), None
    else:
        bundle, snapshot_issue = _archived_design_bundle(record, archive_directory)
    snapshot_source = ('live' if design_run is not None else 'archive') if bundle is not None else None
    from config_io import decode_config
    design_spec = (bundle or {}).get('base_spec') or record.get('adopted_config') or record.get('original_config')
    design_spec = decode_config(design_spec) if isinstance(design_spec, dict) else None
    evidence = _evidence(record, spice_result)
    voltage_observations = _voltage_observations(evidence)
    transformer = record.get('field') or (record.get('transformer') or {}).get('record') or {}
    field = transformer.get('field') or {}
    conditions = transformer.get('model_conditions') or {}
    margin = record.get('margin') or (record.get('transformer') or {}).get('margin') or {}
    calculation = record.get('calculation') or {}
    metrics = distinct_endpoint_metrics(calculation.get('endpoint_metrics') or [],
                                        comparison=transformer.get('before') or ())
    topology = (design_spec or {}).get('topology') or transformer.get('topology')
    from report_docx import TOPOLOGY
    case_label = _input_label(design_spec)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M UTC+08:00')
    subtitle = '  |  '.join(filter(None, (TOPOLOGY.get(topology, topology), case_label, stamp)))
    doc = new_document('电磁仿真，电路仿真，设计计算联合报告', subtitle,
                       '开关电源设计与环路分析  联合评审')
    module_section(doc, '1 评审结论', new_page=False)
    stages = record.get('stages') or []
    review = _joint_review(record, design_spec, bundle, evidence, snapshot_issue)
    acceptance = review['acceptance']
    simulation = review['simulation']
    unique_errors, review_rows = review['unique_errors'], review['review_rows']
    pending, state = review['pending'], review['state']
    workflow, verdict = review['workflow'], review['verdict']
    workflow_incomplete = review['workflow_incomplete']
    lead = conclusion_line(doc, verdict, state)
    lead.paragraph_format.keep_with_next = True
    group_line = acceptance_group_line(acceptance or {})
    if group_line:
        paragraph(doc, group_line, True)
    exceeded = review['exceeded']
    paragraph(doc, f'验收超限 {len(exceeded)} 项，待补数据 {pending} 项。{workflow}。', True)
    if exceeded:
        table(doc, ['验收超限项', '当前值与限值'], exceeded[:4], [2.3, 4.8])
        if len(exceeded) > 4:
            paragraph(doc, f'其余 {len(exceeded) - 4} 项见第 6 章。', True)
    if review_rows:
        table(doc, ['流程与仿真复核', '本次观察与要求'], review_rows[:4], [2.3, 4.8])
        if len(review_rows) > 4:
            paragraph(doc, f'其余 {len(review_rows) - 4} 项见对应章节。', True)
        if simulation.get('comparison_tolerance_pct') is not None and simulation.get('findings'):
            paragraph(doc, f"计算与仿真偏差复核线 {_number(simulation['comparison_tolerance_pct'])}%。", True)
    if simulation.get('state') == 'pass':
        paragraph(doc, '电路仿真  '+simulation['conclusion'], True)
    missing = missing_evidence_note(acceptance or {})
    if missing:
        paragraph(doc, missing, True)
    _key_results(doc, field, margin, metrics, voltage_observations)
    paragraph(doc, '从第 3 章的场解与采用矩阵追溯参数，再对读第 4 章的设计计算和第 5 章的电路仿真。'
              + ('第 6 章记录验收依据。' if acceptance is not None else '')
              + '第 7 章可定位原始证据。', True)

    module_section(doc, '2 共同需求与运行记录', new_page=False)
    if design_spec is not None and bundle is None:
        rails = design_spec.get('outputs') or [design_spec]
        table(doc, ['输出', '电压 / V', '功率 / W', '反馈'], [
            (f'OUT{i}', _number(rail.get('V_out')), _number(rail.get('P_out')),
             '主反馈' if i == design_spec.get('feedback_output', 1) else '—')
            for i, rail in enumerate(rails, 1)
        ], [1.4, 1.8, 1.8, 2.1])
    table(doc, ['步骤', '结论', '耗时 / s', '记录'], [
        (_stage_name(s, record), _STEP_STATES.get(s.get('status'), s.get('status', '未记录')),
         _number(s.get('elapsed_s')), s.get('error') or s.get('message') or '—')
        for s in stages
    ] or [('联合流程', '待补阶段记录', '—', '—')], [1.55, 1.05, .85, 3.65])
    for error in unique_errors:
        paragraph(doc, error, True)
    if record.get('resumed_field'):
        paragraph(doc, '场解耗时为本次校验与衔接时间。', True)
    module_section(doc, '3 变压器场解与参数回填', new_page=False)
    if field:
        material, core, solver = (conditions.get(k) or {} for k in ('material', 'core', 'solver'))
        bobbin = conditions.get('bobbin') or {}
        table(doc, ['项目', '采用条件'], [
            ('磁芯', str(core.get('calculator_core_model') or '未记录')),
            ('材料与相对磁导率', str(material.get('name') or '未记录') + ' / ' + _number(material.get('relative_permeability'))),
            ('骨架净窗口 宽 × 高 / mm', _number(bobbin.get('axial_window_m'), 1e3) + ' × ' + _number(bobbin.get('radial_window_m'), 1e3)),
            ('从内到外的物理层', ' → '.join(f'{name} {turns}匝' for name, turns in conditions.get('layers', [])) or '未记录'),
            ('绕组总匝数', ' / '.join(f'{name} {turns}匝' for name, turns in conditions.get('windings', [])) or '未记录'),
            ('实际模型总气隙 / mm', _number(core.get('total_gap_m'), 1e3)),
            ('磁静态工作点', _number(material.get('temperature_C'), suffix=' °C') + ' / ' + _number(material.get('bias_current_A'), suffix=' A偏置')),
            ('网格与空气域半径', str(solver.get('mesh_profile') or '未记录') + ' / ' + _number(solver.get('air_radius_m'), 1e3, ' mm')),
        ], [2.3, 4.8])
        validation = transformer.get('validation') or {}
        paragraph(doc, '验证记录  ' + '，'.join(name + ('已验证' if validation.get(key) else '待验证')
             for key, name in [('mesh_converged', '网格收敛'), ('air_domain_converged', '空气域收敛'), ('measurement_validated', '样机实测')]) + '。', True)
    else:
        paragraph(doc, '场解数据待补。')

    if margin:
        module_section(doc, '漏感裕量', level=2, new_page=False)
        paragraph(doc, f"原边短路电感按 {_number(margin.get('factor'))} 倍设置。"
                  f"各绕组自感沿用场解，互感统一乘以 {_number(margin.get('off_diagonal_scale'))}。")
        equation(doc, 'M_ij,采用=α×M_ij,场解')
        equation(doc, 'k_ij=', 'M_ij', '√(L_ii×L_jj)')
        paragraph(doc, '式中，i、j 为按报告顺序排列的绕组端口，Mij 为两端口互感（H），Lii、Ljj 为各端口开路自感（H）。α 是互感缩放系数，kij 是两端口耦合系数，均为无量纲。', True)
    elif field:
        paragraph(doc, '参数回填待完成。')
    _matrices(doc, field, margin)
    if margin:
        ports = margin.get('port_order') or field.get('port_order') or []
        old_short = margin.get('original_short_by_port_H') or []
        new_short = margin.get('adopted_short_by_port_H') or []
        if len(old_short) == len(new_short) == len(ports) and ports:
            module_section(doc, '各端口短路电感', level=2, new_page=False)
            table(doc, ['端口', '场解 / µH', '工程采用 / µH', '实际倍数'], [
                (name, _number(old, 1e6), _number(new, 1e6), _number(new / old) if old and new is not None else '—')
                for name, old, new in zip(ports, old_short, new_short)
            ], [1., 2., 2., 2.1])
            paragraph(doc, '测量各端口时，其余端口均为理想短路。', True)
    if field:
        images, image_notes = _field_images(transformer.get('report_path'))
        for index, (blob, caption) in enumerate(images, 1):
            figure(doc, blob, f'变压器图 {index}  {caption}')
        for note in image_notes:
            paragraph(doc, note, True)

    module_section(doc, '4 采用回填参数后的设计计算', new_page=bundle is not None)
    if snapshot_issue:
        paragraph(doc, snapshot_issue + (' 本节列出已保存的端点摘要。' if metrics else ''), True)
    if bundle is not None:
        if snapshot_source == 'archive':
            paragraph(doc, '计算结果来自本次联合运行保存的设计快照。', True)
        from input_range_report import export_input_range_docx
        compensation = (record.get('adopted_config') or {}).get('__comp')
        export_input_range_docx(None, bundle, compensation_state=compensation, document=doc,
                                save=False, include_acceptance=False, chapter_prefix='4.', chapter_level=2)
    elif metrics:
        table(doc, ['工况', '频率 / kHz', 'MOS 电流峰值 / A', 'MOS 电压峰值 / V', '效率 / %'], [
            ('固定输入' if len(metrics) == 1 and case_label.startswith('固定输入') else
             f"{r.get('case', '')} {_number(r.get('vin_V'))} V", _number(r.get('frequency_Hz'), .001),
             _number(r.get('switch_peak_A')), _number(r.get('switch_stress_V')),
             _number(r.get('efficiency'), 100)) for r in metrics
        ], [1.7, 1.2, 1.55, 1.55, 1.1])
        for error in calculation.get('loop_errors') or []:
            paragraph(doc, f"{error.get('case', '')} 环路待复核  {error.get('error', '')}", True)
    else:
        paragraph(doc, '采用矩阵后的计算结果待补。')

    if evidence is not None:
        from spice_comparison_report import write_report
        write_report(None, evidence, document=doc, save=False, include_conclusion=False, section_number=5)
    else:
        module_section(doc, '5 电路仿真与设计对照', new_page=False)
        paragraph(doc, '电路仿真数据待补。')

    if acceptance is not None:
        add_acceptance_report(doc, design_spec, bundle, joint_record=record,
                              spice_evidence=evidence, title='6 工程验收与证据', snapshot=acceptance)
    trace_start = len(doc.paragraphs)
    module_section(doc, '7 适用范围与证据追溯', new_page=False)
    if field:
        paragraph(doc, '线性磁静态场解用于提取自感与互感。交流磁损、饱和和绕组寄生电容需另行评估。', True)
    if evidence:
        paragraph(doc, '电路仿真采用行为模型。原始波形、工况和各阶段的模型条件见随附工程。', True)
    coupling = (design_spec or {}).get('coupling_config') or {}
    if topology == 'QR-FLYBACK' and margin and coupling.get('field_matrix_enabled') and not coupling.get('enabled'):
        paragraph(doc, '本次 QR 设计复算使用原边短路电感折算的标量 K。电路仿真使用完整矩阵。', True)
    if transformer.get('limits') or record.get('limits') or margin.get('notes'):
        paragraph(doc, '场解、参数回填和复算的完整条件见联合记录与原始场解报告。', True)
    trace_table = table(doc, ['证据', '记录'], [
        ('源几何 SHA-256', transformer.get('geometry_sha256') or '未取得'),
        ('场解结果 SHA-256', transformer.get('field_result_sha256') or '未取得'),
        ('求解工具版本', transformer.get('solver_version') or '未取得'),
        ('漏感裕量映射', margin.get('method') or '未取得'),
        ('计算快照 ID', calculation.get('snapshot_id') or '未取得'),
        ('原始运行目录', record.get('directory') or '见随附工程'),
        ('证据执行起止', f"{record.get('started_at') or '未记录'} 至 {record.get('completed_at') or '未记录'}"),
        ('电路计算快照文件', Path(str(calculation['snapshot_path'])).name if calculation.get('snapshot_path') else '未取得'),
        ('实际电路仿真证据文件', Path(str((record.get('circuit') or {}).get('evidence_path'))).name if evidence and (record.get('circuit') or {}).get('evidence_path') else '见随附电路工程 comparison.json' if evidence else '未取得'),
    ], [1.8, 5.3])
    for p in doc.paragraphs[trace_start:-1]:
        p.paragraph_format.keep_with_next = True
    for row in trace_table.rows[:-1]:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.keep_with_next = True
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    finalize_book_report(doc, nested_chapters_under=4)
    doc.save(target)
    return dict(path=str(target), figures=len(doc.inline_shapes), tables=len(doc.tables),
                equations=len(doc.element.xpath('.//m:oMath')), sections=len(doc.sections),
                circuit_evidence_available=evidence is not None,
                complete_design_snapshot=bundle is not None, design_snapshot_source=snapshot_source,
                design_snapshot_issue=snapshot_issue,
                acceptance_state=(acceptance or {}).get('summary', {}).get('state', 'undefined'),
                engineering_accepted=(acceptance or {}).get('summary', {}).get('state') == 'pass',
                incomplete=bool(workflow_incomplete or evidence is None or bundle is None))
