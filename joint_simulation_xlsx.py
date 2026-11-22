"""Joint Excel projection of frozen field, design and actual circuit evidence."""
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from engineering_workbook import band, index, note, page, picture, table, verdict
from joint_simulation_report import (
    _STEP_STATES, _archived_design_bundle, _evidence, _field_images, _input_label,
    _joint_review, _number, _stage_name, _voltage_observations,
)
from xlsx_report_writer import save_workbook


def _scaled(value, multiplier=1.):
    return float(value)*multiplier if isinstance(value,(float,int)) and not isinstance(value,bool) else None


def _configuration(record, bundle):
    from config_io import decode_config

    raw = (bundle or {}).get('base_spec') or record.get('adopted_config') or record.get('original_config')
    try:
        return decode_config(raw) if isinstance(raw,dict) else None
    except (ValueError,TypeError,KeyError):
        return None


def _missing_page(name, title, why, rows=()):
    sheet = page(name,title,'联合流程阶段证据')
    row = verdict(sheet,5,'证据待补',why,'missing')
    if rows:
        table(sheet,row,('工况','计算频率 / kHz','MOS 电流峰值 / A','MOS 电压峰值 / V','计算效率 / %'),
              rows,spans=(2,1,2,2,1))
    return sheet


def _field_sheet(record, transformer, field, margin):
    source = '既有场解经本次输入校验' if record.get('resumed_field') else '本次场解'
    sheet = page('磁件·场解与回填','变压器场解与参数回填',source+' · 线性零偏置磁静态')
    if not field:
        verdict(sheet,5,'场解证据待补','本次记录未取得有效矩阵。',state='missing')
        return sheet
    conditions=transformer.get('model_conditions') or {}
    material, core, solver, bobbin = (conditions.get(key) or {} for key in ('material','core','solver','bobbin'))
    validations = transformer.get('validation') or {}
    pending = [label for key,label in (
        ('mesh_converged','网格收敛'),('air_domain_converged','空气域收敛'),('measurement_validated','样机实测'))
        if not validations.get(key)]
    label = '已回填工程矩阵' if margin else '已取得场解矩阵，待回填'
    row = verdict(sheet,5,label,
        '待验证 '+ '、'.join(pending) if pending else '已有记录包含网格、空气域和实测验证。',
        'review' if pending or not margin else 'pass')
    row = band(sheet,row,'场解工况')
    row = table(sheet,row,('项目','条件','项目','条件'),[
        ('磁芯',core.get('calculator_core_model'),'材料',material.get('name')),
        ('相对磁导率',material.get('relative_permeability'),'材料温度 / °C',material.get('temperature_C')),
        ('气隙 / mm',_scaled(core.get('total_gap_m'),1e3),'偏置电流 / A',material.get('bias_current_A')),
        ('净窗口 / mm',_number(bobbin.get('axial_window_m'),1e3)+' × '+_number(bobbin.get('radial_window_m'),1e3),
         '空气域半径 / mm',_scaled(solver.get('air_radius_m'),1e3)),
        ('网格配置',solver.get('mesh_profile'),'场解频率 / Hz',material.get('frequency_Hz')),
    ],spans=(2,2,2,2))
    row = note(sheet,row,'物理层由内到外  '+(' → '.join(f'{name} {turns} 匝' for name,turns in conditions.get('layers',[])) or '待记录'))
    row = band(sheet,row+1,'漏感裕量与电气采用值')
    row = table(sheet,row,('指标','场解','设计采用','工程口径'),[
        ('原边开路自感 / µH',_scaled(field.get('primary_self_H'),1e6),
         _scaled(margin.get('primary_self_H'),1e6),'采用矩阵时保持自感。'),
        ('原边短路漏感 / µH',_scaled(field.get('primary_short_H'),1e6),
         _scaled(margin.get('adopted_primary_short_H'),1e6),'其余功率端口均理想短接。'),
        ('漏感目标倍数',None,margin.get('factor'),'工程设置。'),
        ('互感统一缩放系数',None,margin.get('off_diagonal_scale'),'对非对角元素 Mij 应用。'),
    ],spans=(2,1,1,4))
    ports = margin.get('port_order') or ()
    old, new = (margin.get(key) or () for key in ('original_short_by_port_H','adopted_short_by_port_H'))
    if ports and len(old) == len(new) == len(ports):
        row = table(sheet,row+1,('测量端口','场解 / µH','采用 / µH','实际倍数'),
            [(name,_scaled(a,1e6),_scaled(b,1e6),b/a if a and b is not None else None)
             for name,a,b in zip(ports,old,new)],spans=(2,2,2,2))
    images, warnings = _field_images(transformer.get('report_path'))
    if images:
        row = band(sheet,row+1,'场解图像')
        from PIL import Image
        for blob, caption in images:
            stream = BytesIO()
            with Image.open(BytesIO(blob)) as raster:
                raster.thumbnail((1500,1250))
                raster.convert('RGB').save(stream,format='PNG')
            row = picture(sheet,row,stream.getvalue(),caption)+1
    for warning in warnings:
        row = note(sheet,row,warning)
    return sheet


def _matrix_sheet(field, margin):
    sheet = page('磁件·原始与采用矩阵','原始与采用矩阵','自感和互感以 µH 表示，kij 为有符号耦合系数')
    row = 5
    if not field and not margin:
        verdict(sheet,row,'矩阵证据待补','当前记录不含可用矩阵。',state='missing')
        return sheet
    row = note(sheet,row,'kij = Mij / √(Lii × Ljj)。i 和 j 对应表头端口，Mij 为两端口互感，Lii 和 Ljj 为开路自感。')
    ports = field.get('port_order') or ()
    selected = margin.get('port_order') or ports
    for key, label, scale in (('L_ports_H','电感矩阵 / µH',1e6),('k_ports','有符号耦合矩阵',1.)):
        before, after = field.get(key) or (), margin.get('adopted_'+key) or ()
        for prefix, names, values in (('场解',ports,before),('采用',selected,after)):
            if prefix == '采用' and before and values == before and list(names) == list(ports):
                row = note(sheet,row,f'采用{label}沿用场解结果。')
                continue
            row = band(sheet,row+1,prefix+label)
            if names and len(names) <= 7 and len(values) == len(names) and all(len(v)==len(names) for v in values):
                row = table(sheet,row,('端口',*names),
                    [(name,*(_scaled(x,scale) for x in value)) for name,value in zip(names,values)])
            else:
                row = note(sheet,row,'当前记录未保存尺寸匹配的矩阵。')
    return sheet


def _trace_sheet(record, transformer, margin, calculation, evidence, topology):
    sheet = page('证据·来源与边界','来源与适用边界')
    circuit = record.get('circuit') or {}
    row = table(sheet,5,('证据','运行记录'),[
        ('冻结输入 ID',record.get('input_id')),
        ('源几何 SHA-256',transformer.get('geometry_sha256')),
        ('场解结果 SHA-256',transformer.get('field_result_sha256')),
        ('求解工具版本',transformer.get('solver_version')),
        ('裕量映射方法',margin.get('method')),
        ('计算快照 ID',calculation.get('snapshot_id')),
        ('计算快照文件',Path(calculation['snapshot_path']).name if calculation.get('snapshot_path') else None),
        ('开关证据',Path(circuit['evidence_path']).name if evidence is not None and circuit.get('evidence_path') else
         '随附电路工程 comparison.json' if evidence is not None else None),
        ('运行起始',record.get('started_at')),('运行完成',record.get('completed_at')),
    ],spans=(2,6))
    row = band(sheet,row+1,'适用边界')
    if topology == 'QR-FLYBACK' and margin:
        spec = _configuration(record,None) or {}
        coupling = spec.get('coupling_config') or {}
        if coupling.get('field_matrix_enabled') and not coupling.get('enabled'):
            row = note(sheet,row,'本次 QR 设计复算用原边短路电感折算的标量 K，电路采用完整矩阵。')
    principles = (record.get('limits') or []) + (transformer.get('limits') or []) + (margin.get('notes') or [])
    for text in dict.fromkeys(str(x) for x in principles):
        row = note(sheet,row,text)
    return sheet


def _acceptance_sheet(snapshot, bundle, spec):
    from report_architecture import acceptance_columns, missing_evidence_note
    from report_xlsx import write_acceptance_details
    from xlsx_report_writer import WIDTHS

    labels, rows = acceptance_columns(snapshot, bundle, spec)
    width = 8 if len(labels) == 1 else 17
    sheet = page('证据·工程验收','工程验收',
                 '计算、仿真和实测按同一工况和判据分别记载。', widths=WIDTHS[:width])
    summary = snapshot.get('summary') or {}
    missing = missing_evidence_note(snapshot)
    state = summary.get('state') or 'missing'
    row = verdict(sheet,5,summary.get('label') or '验收证据待补',missing,
                  'fail' if state == 'review' else state)
    write_acceptance_details(sheet, row+1, snapshot, labels, rows)
    return sheet


def write_joint_xlsx(path, record, *, design_run=None, spice_result=None, archive_directory=None):
    """Export from the current immutable calculation or its verified archive snapshot."""
    from report_architecture import acceptance_group_line

    bundle, snapshot_issue = ((design_run.runtime_bundle(),None) if design_run is not None else
                              _archived_design_bundle(record, archive_directory))
    if bundle is not None and not isinstance(bundle.get('base_spec'),dict):
        bundle, snapshot_issue = None, '设计快照缺少冻结输入，当前工作表保留已有端点摘要。'
    spec = _configuration(record,bundle)
    circuit_issue = None
    try:
        evidence = _evidence(record,spice_result)
    except (OSError,ValueError,BadZipFile):
        evidence, circuit_issue = None, '开关证据文件无法读取。'
    transformer = record.get('field') or (record.get('transformer') or {}).get('record') or {}
    field = transformer.get('field') or {}
    margin = record.get('margin') or (record.get('transformer') or {}).get('margin') or {}
    calculation = record.get('calculation') or {}
    topology = (spec or {}).get('topology') or transformer.get('topology')
    from report_docx import TOPOLOGY
    context = '  ·  '.join(filter(None, (TOPOLOGY.get(topology,topology),_input_label(spec),record.get('started_at'))))
    review = _joint_review(record,spec,bundle,evidence,snapshot_issue)
    title = '电磁仿真，电路仿真，设计计算联合报告'
    cover = page('联合结论',title,context,freeze_rows=0)
    evidence_missing = not (field and margin and bundle is not None and evidence and evidence.get('cases'))
    state = 'fail' if review['state'] == 'review' else review['state']
    exceeded = review['exceeded']
    group_line = acceptance_group_line(review['acceptance'] or {})
    row = verdict(cover,5,review['verdict'],
                  f"验收超限 {len(exceeded)} 项，待补数据 {review['pending']} 项。{review['workflow']}。",
                  state)
    if group_line:
        row = note(cover, row, group_line)
    if evidence_missing:
        names = [name for label,name in ((field,'场解'),(margin,'回填矩阵'),(bundle is not None,'计算快照'),
                 (evidence and evidence.get('cases'),'电路试验')) if not label]
        row = note(cover,row,'未取得的主要证据  '+ '、'.join(names)+'。')
    if exceeded:
        row = band(cover, row+1, '验收超限项')
        row = table(cover, row, ('项目', '当前值与限值'), exceeded[:6], spans=(2,6))
        if len(exceeded) > 6:
            row = note(cover, row, f'其余 {len(exceeded)-6} 项见「证据·工程验收」。')
    if review['review_rows']:
        row = band(cover,row+1,'流程与仿真复核')
        row = table(cover,row,('项目','观察与要求'),review['review_rows'][:6],spans=(2,6))
        if len(review['review_rows'])>6:
            row = note(cover,row,f"其余 {len(review['review_rows'])-6} 项见「证据·优先复核」。")
    row = band(cover,row+1,'关键观测')
    measurements = [('场解原边自感 / µH',_scaled(field.get('primary_self_H'),1e6),'变压器磁静态'),
                    ('场解原边短路漏感 / µH',_scaled(field.get('primary_short_H'),1e6),'其余端口理想短路'),
                    ('采用原边短路漏感 / µH',_scaled(margin.get('adopted_primary_short_H'),1e6),'裕量回填值')]
    for key, name in (('vds_peak','稳态 MOS Vds 峰值 / V'),('startup_vds_peak','启动 MOS Vds 峰值 / V')):
        extremes=[(obs[key],case.get('id','')) for case,obs in _voltage_observations(evidence) if obs.get(key) is not None]
        if extremes:
            value, case = max(extremes)
            measurements.append((name,value,case))
    row = table(cover,row,('关键量','结果','来源或工况'),measurements,spans=(3,2,3))
    row = band(cover,row+1,'本次工作流')
    row = table(cover,row,('阶段','状态','耗时 / s','处置与依据'),[
        (_stage_name(stage,record),_STEP_STATES.get(stage.get('status'),'待补记录'),stage.get('elapsed_s'),
         stage.get('error') or stage.get('message') or '详见对应工作表')
        for stage in record.get('stages') or ()],spans=(2,1,1,4),state_col=1)
    fields = [_field_sheet(record,transformer,field,margin),_matrix_sheet(field,margin)]
    if bundle is not None:
        from report_xlsx import build_input_range_xlsx_sheets
        design, _ = build_input_range_xlsx_sheets(bundle,
            compensation_state=(record.get('adopted_config') or {}).get('__comp'), sheet_prefix='设计·',
            acceptance=review['acceptance'])
    else:
        from transformer_sim_report import distinct_endpoint_metrics
        metrics = distinct_endpoint_metrics(calculation.get('endpoint_metrics') or [],comparison=transformer.get('before') or ())
        design = [_missing_page('设计·设计计算','采用参数后的设计计算',
                   snapshot_issue or '本次运行没有可展开的设计计算快照。',[
                       (case.get('case'),_scaled(case.get('frequency_Hz'),.001),case.get('switch_peak_A'),
                        case.get('switch_stress_V'),_scaled(case.get('efficiency'),100.)) for case in metrics])]
    if evidence and evidence.get('cases'):
        from spice_comparison_xlsx import build_sheets
        circuit = build_sheets(evidence,prefix='电路·')
    else:
        circuit = [_missing_page('电路·仿真对照','电路仿真与设计对照',circuit_issue or '本次记录没有可使用的开关试验证据。')]
    trace = _trace_sheet(record,transformer,margin,calculation,evidence,topology)
    acceptance = _acceptance_sheet(review['acceptance'],bundle,spec) if review['acceptance'] else None
    entries = [
        (fields[0].name,'场解与回填','磁芯、绕组、求解条件、回填步骤和场图'),
        (fields[1].name,'L / k 矩阵','逐端口追溯场解和实际采用值'),
        (design[0].name,'采用参数后的设计计算','与独立计算报告共用格式，按工况展开'),
        (circuit[0].name,'开关仿真对照','实际黑盒、白盒、波形和测试覆盖'),
    ]
    evidence_sheets = []
    if acceptance:
        entries.append((acceptance.name,'工程验收','计算、开关仿真与实测凭据同判据对照'))
        evidence_sheets.append(acceptance)
    entries.append((trace.name,'来源与边界','运行编号、证据哈希和假设'))
    evidence_sheets.append(trace)
    if len(review['review_rows'])>6:
        check = page('证据·优先复核','流程与仿真复核','按本次联合流程和电路试验记录汇总')
        table(check,5,('项目','观察与要求'),review['review_rows'],spans=(2,6))
        entries.append((check.name,'全部复核项目','定位未通过或待核的测试条件'))
        evidence_sheets.append(check)
    index(cover,row+1,entries)
    sheets = [cover,*fields,*design,*circuit,*evidence_sheets]
    target = Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    save_workbook(target,sheets)
    return dict(path=str(target),sheets=len(sheets),figures=sum(len(s.images) for s in sheets),
                complete_design_snapshot=bundle is not None,circuit_evidence_available=bool(evidence and evidence.get('cases')),
                state=state,incomplete=bool(review['workflow_incomplete'] or evidence_missing))
