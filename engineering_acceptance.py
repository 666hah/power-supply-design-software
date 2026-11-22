"""Traceable engineering acceptance data, never a second physical solver.

Version 1 stores user targets, manually entered measurements and issue history.
All numerical design values are projections of already completed snapshots.
An input hash is an identity guard, not an instrument authenticity certificate.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math

from loop_acceptance import MIN_PHASE_MARGIN_DEG

SCHEMA = 'power-design.engineering-acceptance.v1'
VERSION = 1
SOURCES = ('calculation', 'simulation', 'measurement')
CASE_IDS = ('Vinmin', 'Vinmax')
GROUPS = (('components', '器件规格'), ('performance', '电源外特性'))
STATE_LABELS = {'pass': '满足', 'review': '超限',
                'undefined': '待补规格或结果', 'stale': '证据已失效',
                'na': '不适用'}
_DISPLAY_KEYS = {'input_voltage_case', 'ui_font_size', 'font_size', 'display_voltage_case',
                 'sweep_var', 'sweep_min', 'sweep_max', 'sweep_n'}


def _text(value, field, *, limit=8000):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{field} 应为不超过 {limit} 字的文字')
    return value.strip()


def _finite(value, field):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{field} 必须为有限数值或空值')
    return float(value)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def normalize(value=None):
    """Validate a config or a complete spec; return an owned JSON-safe config."""
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ValueError('engineering_acceptance 应为对象')
    if 'engineering_acceptance' in value:
        value = value.get('engineering_acceptance')
        value = {} if value is None else value
    if (not isinstance(value, dict) or type(value.get('version', 1)) is not int or
            value.get('version', 1) != 1):
        raise ValueError('不支持的工程验收配置版本')
    result = dict(version=1, criteria=[], measurements=[], issues=[])
    for group in ('criteria', 'measurements', 'issues'):
        rows = value.get(group, [])
        if not isinstance(rows, list) or len(rows) > 5000:
            raise ValueError(group + ' 应为不超过5000项的列表')
        used = set()
        for index, source in enumerate(rows):
            if not isinstance(source, dict):
                raise ValueError(group + ' 每项必须为对象')
            row = dict(id=_text(source.get('id'), group + '.id', limit=160))
            if not row['id'] or row['id'] in used:
                raise ValueError(group + ' 的 id 不能为空或重复')
            used.add(row['id'])
            if group == 'criteria':
                row.update(metric=_text(source.get('metric', row['id']), 'metric', limit=160),
                    name=_text(source.get('name'), 'name', limit=240),
                    unit=_text(source.get('unit'), 'unit', limit=40),
                    comparison=source.get('comparison', '<='),
                    limit=_finite(source.get('limit'), 'limit'),
                    lower=_finite(source.get('lower'), 'lower'),
                    upper=_finite(source.get('upper'), 'upper'),
                    note=_text(source.get('note'), 'note'),
                    enabled=source.get('enabled', True),
                    required_sources=copy.deepcopy(source.get('required_sources', list(SOURCES))))
                if row['comparison'] not in ('<=', '>=', '<', '>', 'range'):
                    raise ValueError('阈值关系应为 <=、>=、<、> 或 range')
                if not isinstance(row['enabled'], bool):
                    raise ValueError('enabled 必须为布尔值')
                if (not isinstance(row['required_sources'], list) or not row['required_sources'] or
                        any(s not in SOURCES for s in row['required_sources']) or
                        len(set(row['required_sources'])) != len(row['required_sources'])):
                    raise ValueError('required_sources 应为不重复的计算/仿真/实测来源列表')
                if row['comparison'] == 'range' and row['lower'] is not None and row['upper'] is not None and row['lower'] > row['upper']:
                    raise ValueError('阈值下限不能大于上限')
            elif group == 'measurements':
                row.update(criterion_id=_text(source.get('criterion_id'), 'criterion_id', limit=160),
                    case_id=source.get('case_id'), value=_finite(source.get('value'), 'measurement.value'),
                    source=_text(source.get('source'), 'measurement.source', limit=1000),
                    conditions=_text(source.get('conditions'), 'measurement.conditions'),
                    evidence_ref=_text(source.get('evidence_ref'), 'measurement.evidence_ref', limit=2000),
                    note=_text(source.get('note'), 'measurement.note'),
                    input_fingerprint=_text(source.get('input_fingerprint'), 'measurement.input_fingerprint', limit=100),
                    recorded_at=_text(source.get('recorded_at'), 'recorded_at', limit=100),
                    origin='manual-entry')
                if row['case_id'] not in CASE_IDS or not row['criterion_id']:
                    raise ValueError('实测必须指定指标及 Vinmin/Vinmax')
            else:
                row.update(title=_text(source.get('title'), 'issue.title', limit=240),
                    description=_text(source.get('description'), 'issue.description'),
                    action=_text(source.get('action'), 'issue.action'),
                    owner=_text(source.get('owner'), 'issue.owner', limit=160),
                    status=source.get('status', 'open'),
                    evidence=_text(source.get('evidence'), 'issue.evidence'),
                    input_fingerprint=_text(source.get('input_fingerprint'), 'issue.input_fingerprint', limit=100),
                    updated_at=_text(source.get('updated_at'), 'issue.updated_at', limit=100))
                if row['status'] not in ('open', 'in_progress', 'closed'):
                    raise ValueError('整改状态应为 open、in_progress 或 closed')
            result[group].append(row)
    return result


def _canonical_inputs(parameters):
    """Resolve active SI ownership without calculating physical operating points.

    Defaults are expanded without calculating or validating feasibility. Fields
    beginning with '_' are engine internals / saved provenance, never user
    electrical inputs. Nested physical winding positions and curve points stay.
    """
    if not isinstance(parameters, dict):
        raise ValueError('设计输入应为对象')
    from config_io import decode_config
    from power_stage import DEFAULT_PARAMS
    p = copy.deepcopy(DEFAULT_PARAMS)
    decoded = decode_config(parameters)
    p.update(decoded)
    present = ('V_in_min' in decoded, 'V_in_max' in decoded)
    if any(present) and not all(present):
        raise ValueError('输入电压范围必须同时有上下限才能匹配证据')
    if not any(present) and 'V_in' in decoded:
        p['V_in_min'] = p['V_in_max'] = decoded['V_in']
    # Reuse ownership rules, never compare UI compatibility mirrors as extra
    # independent hardware. Every actual branch remains in the canonical data.
    from capacitor_banks import normalize as normalize_capacitors
    p = normalize_capacitors(p)
    if p.get('outputs'):
        from isolated_outputs import output_specs, selected_params
        rails = output_specs(p)
        p = selected_params(p, rails)
        p['outputs'] = [{key: value for key, value in r.items() if key != 'id'} for r in rails]
    from mos_manual import manual_platform, normalize_events
    if manual_platform(p):
        p['mos_manual_events'] = normalize_events(p.get('mos_manual_events'), p)
        for key in ('Vgp_on', 'Vgp_off', 'Qgs'):
            p.pop(key, None)  # overridden by explicit/legacy-expanded events
    coupling = p.get('coupling_config') or {}
    if not coupling.get('enabled') and not coupling.get('field_matrix_enabled'):
        p['coupling_config'] = dict(enabled=False, field_matrix_enabled=False)
    else:
        # DCR has been geometric, not an editable winding-model input, since
        # TRANSFORMER_ELECTRICAL. Preserve the actual k/self-L/port order.
        p['coupling_config'] = {key: value for key, value in coupling.items() if key != 'dcr'}
    if coupling.get('enabled') or p.get('topology') == 'ACF-FORWARD':
        p.pop('K', None)  # matrix leakage / active clamp owns this quantity
    if p.get('topology') in ('BUCK', 'BOOST', 'BUCK-BOOST'):
        p.pop('K', None)
        p.pop('Kc', None)  # flyback RCD controls have no nonisolated owner
    if p.get('winding_config'):
        winding = copy.deepcopy(p['winding_config'])
        actual_windings = {'P'} | {f'OUT{i}' for i in range(1, len(p.get('outputs') or [1])+1)}
        if p.get('feedback_mode') == 'PSR-MP6005':
            actual_windings.add('AUX')
        winding['overrides'] = {key: value for key, value in (winding.get('overrides') or {}).items()
                               if key in actual_windings}
        p['winding_config'] = winding
    for key in ('tr', 'tf', 'le_core'):
        p.pop(key, None)  # legacy edge times / le have no active formula owner
    p.pop('engineering_acceptance', None)
    for key in tuple(p):
        if key.startswith('_') or key in _DISPLAY_KEYS:
            p.pop(key, None)
    if 'V_in_min' in p and 'V_in_max' in p:
        p.pop('V_in', None)
    # JSON numbers 1 and 1.0 have identical engineering meaning.
    def canonical(value):
        if isinstance(value, dict):
            return {str(k): canonical(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                raise ValueError('输入包含非有限数，不能匹配证据')
            return float(format(float(value), '.15g'))
        if hasattr(value, 'tolist'):
            return canonical(value.tolist())
        raise ValueError('输入包含非JSON数据，不能匹配证据')
    return canonical(p)


def input_fingerprint(parameters):
    """Hash active inputs; UI drafts, legacy mirrors and evidence are excluded."""
    blob = json.dumps(_canonical_inputs(parameters), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _base_spec(bundle):
    return bundle.get('base_spec', bundle.get('spec')) if isinstance(bundle, dict) else None


def _matches(spec, fingerprint):
    try:
        return isinstance(spec, dict) and input_fingerprint(spec) == fingerprint
    except (ValueError, TypeError):
        return False


def _cases(bundle):
    rows = bundle.get('cases', []) if isinstance(bundle, dict) else []
    if isinstance(bundle, dict) and not rows and (bundle.get('res') or bundle.get('result')):
        base = bundle.get('base_spec') or bundle.get('p') or {}
        case_id = 'Vinmax' if base.get('input_voltage_case') == 'max' else 'Vinmin'
        rows = [dict(id=case_id, result=bundle.get('res') or bundle.get('result'),
                     checks=bundle.get('checks', []), loop_error=bundle.get('loop_error'))]
    return {row.get('id'): row for row in rows if isinstance(row, dict) and row.get('id') in CASE_IDS}


def _check_index(case):
    res = case.get('result') or case.get('res') or {}
    return {check['id']: check for check in (case.get('checks') or res.get('checks') or [])
            if check.get('id')} if not case.get('error') else {}


def _metric(key, name, unit, comparison, limit, note='', *, group='components'):
    return dict(id=key, metric=key, name=name, unit=unit, comparison=comparison,
                limit=_number(limit), lower=None, upper=None, note=note, group=group)


def _magnetic_rows(p):
    """Keep both magnetic limits visible even if a device has no valid model."""
    from cot_settings import active
    common = dict(
        B=('峰值磁密', 'T', '<', p['Bsat']),
        T=('温升', 'K', '<=', p['temp_rise_limit']),
    )
    topo = p['topology']
    count = len(p.get('outputs') or ())
    devices = []
    if topo in ('FLYBACK', 'QR-FLYBACK', 'LLC', 'ACF-FORWARD'):
        suffix = '_T' if topo in ('LLC', 'ACF-FORWARD') else ''
        devices.append(('T1 变压器', {'B': 'B_sat'+suffix, 'T': 'temp_rise'+suffix}))
    if topo == 'ACF-FORWARD' and count:
        devices.extend((f'L_O{i} 输出电感', {key: f'OUT{i}_L_{key}' for key in common})
                       for i in range(1, count+1))
    elif topo not in ('FLYBACK', 'QR-FLYBACK'):
        if active(p):
            devices.extend((f'PH{i} 电感', {key: f'cot_phase_{i}_{key}' for key in common})
                           for i in range(1, int(p.get('buck_phases', 1))+1))
        else:
            suffix = '_L' if topo in ('LLC', 'ACF-FORWARD') else ''
            ref = 'L_R 谐振电感' if topo == 'LLC' else 'L1 电感'
            devices.append((ref, {'B': 'B_sat'+suffix, 'T': 'temp_rise'+suffix}))
    return [_metric(ids[key], ref+' '+label, unit, comparison, limit,
                    '限值来自磁件参数。峰值磁密按绝对峰值，温升按环境以上增量。')
            for ref, ids in devices for key, (label, unit, comparison, limit) in common.items()]


def _acceptance_metrics(p, calculation_checks):
    """Register only the specified component limits and external targets."""
    from component_management import evaluate_components
    from isolated_outputs import output_specs

    published = {key: check for checks in calculation_checks.values() for key, check in checks.items()}
    component_checks = evaluate_components(p)['checks']
    rows = []
    for item in component_checks:
        key = item['id']
        if item['metric'] == 'spike':  # generic diode follow-up is already covered by reverse voltage
            continue
        if item['metric'] == 'peak' and not any(
                _number(checks.get(key, {}).get('value')) is not None for checks in calculation_checks.values()):
            continue  # no modeled repeatable peak distinct from the blocking platform
        check = published.get(key, item)
        name = check.get('name', item['name'])
        note = '限值来自器件 BOM 与规格。'
        if item['metric'] == 'peak':
            name = f"{item['ref']} MOS 模型峰值 Vds"
            note += '使用模型峰值适用的降额限值。'
        elif item['metric'] == 'voltage' and item['ref'].startswith('Q'):
            name = f"{item['ref']} MOS 漏源电压 Vds"
            note += '计算采用阻断平台。仿真采用有效测量窗的峰值。'
        rows.append(_metric(key, name, item['unit'], '<=', check.get('limit'), note))
    rows.extend(_magnetic_rows(p))
    for index, rail in enumerate(output_specs(p) or [p], 1):
        target = rail.get('ripple_target', p['ripple_target']) * abs(rail['V_out'])
        rows.append(_metric(f'out{index}_ripple', f'OUT{index} 低频输出纹波', 'V', '<=', target,
                            '限值来自需求中的纹波目标。计算值为低频峰峰值。', group='performance'))
    rows.extend((
        _metric('phase_margin', '最小相位裕度', 'deg', '>', MIN_PHASE_MARGIN_DEG,
                '取所有有效 0 dB 穿越中的最小相位裕度。', group='performance'),
        _metric('eta', '效率', '', '>=', p['target_eta'],
                '使用需求中的效率目标。录入 0.93 表示 93%。', group='performance'),
    ))
    return rows


def _calculated_item(criterion, case, checks):
    key = criterion['id']
    if not case or case.get('error'):
        return None, criterion['limit']
    res = case.get('result') or case.get('res') or {}
    if key == 'phase_margin':
        return _number((res.get('loop') or {}).get('min_pm')), criterion['limit']
    if key == 'eta':
        return _number(res.get('eta')), criterion['limit']
    if criterion['group'] == 'performance':
        index = int(key.removeprefix('out').removesuffix('_ripple'))
        rails = res.get('outputs') or [dict(ripple_pp=(res.get('wf') or {}).get('ripple_pp'))]
        check = checks.get(f'OUT{index}_ripple') if res.get('outputs') else checks.get('ripple')
        value = rails[index-1].get('ripple_pp') if index <= len(rails) else None
        return _number(value), _number(check.get('limit')) if check else criterion['limit']
    check = checks.get(key)
    if check is None:
        return None, criterion['limit']
    return _number(check.get('value')), _number(check.get('limit'))


def _simulation_values(case):
    measured = case.get('measurements') or {}
    loop = case.get('loop') or {}
    metrics = loop.get('simulation') or loop.get('metrics') or {}
    metrics = metrics.get('loop', metrics)
    values = dict(primary_rms=measured.get('primary_rms'), primary_peak=measured.get('primary_peak'),
                  vds_peak=measured.get('vds_peak'))
    startup = case.get('full_transient') or case.get('startup_extrema') or {}
    # QR's existing full-transient scan is stored separately from plotted data.
    values['startup_vds_peak'] = startup.get('vds_peak_full_v')
    for container in (case.get('startup') or {}, case.get('runtime') or {}, case.get('full_run') or {}, case.get('qr_startup') or {}):
        if isinstance(container, dict) and container.get('vds_peak_full_v') is not None:
            values['startup_vds_peak'] = container['vds_peak_full_v']
    if loop.get('available'):
        values.update(fc=metrics.get('fc'), phase_margin=metrics.get('pm'), gain_margin=metrics.get('gm_db'))
    for key, value in measured.items():
        if not key.startswith('out'):
            continue
        for suffix, target in (('_before', '_voltage'), ('_pre_ripple', '_ripple'),
                               ('_winding_rms', '_rms'), ('_winding_peak', '_peak')):
            if key.endswith(suffix):
                values[key[:-len(suffix)] + target] = value
    return {k: _number(v) for k, v in values.items()}


def _simulation_acceptance_values(case, *, multi_output):
    """Project qualified electrical stress evidence using measured quantities and units."""
    if not case:
        return {}
    from spice_white_box import bom_reference
    periodicity = case.get('periodicity')
    stable = (periodicity.get('stable') if isinstance(periodicity, dict)
              else bool(case.get('phase_table') and case.get('steady_before_step', {}).get('passed')))
    qualified = bool(case.get('complete') and case.get('nominal_comparable') and stable
                     and not case.get('protection_stop'))
    values = {}

    def record(key, value):
        value = _number(value)
        if value is not None:
            worst = min if key == 'phase_margin' else max
            values[key] = worst(value, values.get(key, value))

    llc = case.get('measured') or {}
    if case.get('status') == '完成' and llc.get('ready') and llc.get('no_gate_overlap'):
        for field, prefix, metric in (
            ('switch_Vds_peak_V', 'Q', 'voltage'), ('diode_Vr_peak_V', 'D', 'voltage'),
            ('switch_I_rms_A', 'Q', 'current_rms'), ('input_bank_rms_A', 'C_IN', 'ripple'),
            ('output_bank_rms_A', 'C_O', 'ripple'),
        ):
            for index, value in enumerate(llc.get(field) or (), 1):
                record(f'bom_{prefix}{index}_{metric}', value)
        record('bom_C_R_voltage', llc.get('V_cr_peak_V'))
        record('bom_C_R_ripple', llc.get('I_res_rms_A'))
        from spice_analysis import llc_fra_phase_margin
        record('phase_margin', llc_fra_phase_margin(case))
    if qualified:
        loop = case.get('loop') or {}
        if loop.get('available'):
            result = loop.get('simulation') or loop.get('metrics') or {}
            result = result.get('loop', result)
            from spice_analysis import minimum_phase_margin
            record('phase_margin', minimum_phase_margin(result))
        window = case.get('white_box') or {}
        if window.get('available'):
            for item in window.get('rows') or ():
                ref = item.get('ref', '')
                label = item.get('metric', '').removeprefix(ref+' ')
                metric = {
                    '纹波 AC RMS': 'ripple', '端电压绝对峰值': 'voltage', '沟道电流 RMS': 'current_rms',
                    '|Vds| 峰值': 'voltage', '反向电压峰值': 'voltage',
                    'If 峰值': 'current_peak', '|Id| 峰值': 'current_peak',
                }.get(label)
                if ref and metric:
                    record(f'bom_{bom_reference(ref, multi_output)}_{metric}', item.get('simulation'))
    # Startup is a separate measurement window. Its voltage peak uses the
    # ordinary per-part voltage limit, regardless of the steady-state window.
    startup = case.get('white_box_startup') or {}
    if case.get('complete') and startup.get('complete_window'):
        for item in startup.get('rows') or ():
            if item.get('channel') == 'voltage' and item.get('kind') in ('mos', 'diode', 'capacitor') and item.get('ref'):
                ref = bom_reference(item['ref'], multi_output)
                record(f'bom_{ref}_voltage', item.get('simulation'))
    return values


def _judge(value, criterion):
    if value is None:
        return 'undefined', None
    operator = criterion['comparison']
    if operator == 'range':
        lo, hi = criterion.get('lower'), criterion.get('upper')
        if lo is None or hi is None:
            return 'undefined', None
        margin = min(value - lo, hi - value)
        return ('pass' if margin >= 0 else 'review'), margin
    limit = criterion.get('limit')
    if limit is None:
        return 'undefined', None
    margin = limit - value if operator in ('<=', '<') else value - limit
    passed = margin > 0 if operator in ('<', '>') else margin >= 0
    return ('pass' if passed else 'review'), margin


def _spice_binding(p, fingerprint, joint_record, spice_evidence, notes):
    envelope = spice_evidence or {}
    if isinstance(envelope, dict) and envelope.get('evidence_error'):
        notes.append('仿真证据引用不可用：' + str(envelope['evidence_error']))
    if isinstance(envelope, dict) and envelope.get('input_fingerprint') == fingerprint and isinstance(envelope.get('evidence'), dict):
        return envelope['evidence'], True, _text(envelope.get('source') or '当前输入绑定的电路仿真记录', 'source')
    if (isinstance(envelope, dict) and envelope.get('schema') == 'powerdesign-spice-comparison-2' and
            envelope.get('input_fingerprint') == fingerprint and isinstance(envelope.get('cases'), list)):
        return envelope, True, '原生电路仿真证据 / 当前输入指纹匹配'
    joint = joint_record or {}
    if isinstance(joint, dict) and isinstance(joint.get('record'), dict):
        joint = joint['record']
    if isinstance(joint, dict) and _matches(joint.get('adopted_config'), fingerprint):
        evidence = (joint.get('circuit') or {}).get('evidence')
        if isinstance(evidence, dict):
            return evidence, True, '联合任务当前采用硬件 / ' + str(joint.get('directory') or '内存记录')
    if envelope or joint:
        notes.append('已有仿真未与当前输入匹配。请采用仿真硬件或打开其工程。')
    return {}, False, '未取得匹配配置的仿真证据'


def _endpoint_simulations(p, spice):
    from mos_manual import distinct_endpoints

    cases = [case for case in spice.get('cases', ()) if isinstance(case, dict) and not case.get('fault_test')]
    shared = p.get('V_in_min') == p.get('V_in_max') and not distinct_endpoints(p)
    multi_output = bool(p.get('outputs') or p.get('feedback_mode') == 'PSR-MP6005')
    result = {}
    for case_id in CASE_IDS:
        vin = p.get('V_in_min' if case_id == 'Vinmin' else 'V_in_max', p.get('V_in'))
        at_vin = [case for case in cases if _number(case.get('voltage')) == _number(vin)]
        sim = next((case for case in at_vin if str(case.get('id', '')).split('_', 1)[0] == case_id), None)
        if sim is None and shared and at_vin:
            sim = at_vin[0]
        result[case_id] = _simulation_acceptance_values(sim, multi_output=multi_output)
    return result


def _summary(rows):
    counts = dict.fromkeys(STATE_LABELS, 0)
    for row in rows:
        for cell in row['cases'].values():
            counts[cell['status']] += 1
    state = ('review' if counts['review'] else 'stale' if counts['stale'] else
             'undefined' if counts['undefined'] or not counts['pass'] else 'pass')
    return dict(state=state, counts=counts, label=STATE_LABELS[state])


def _case_evidence(criterion, case, vin, checks, simulated, measurement, fingerprint, *, origin, stale_calculation):
    value, limit = _calculated_item(criterion, case, checks)
    target = dict(comparison=criterion['comparison'], limit=limit, lower=None, upper=None)
    available = dict(calculation=value, simulation=simulated,
                     measurement=measurement.get('value') if measurement else None)
    usable = {source for source, reading in available.items() if reading is not None}
    states, margins, reasons = {}, {}, []
    for source in SOURCES:
        states[source], margins[source] = _judge(available[source], target)
    if stale_calculation:
        states['calculation'], margins['calculation'] = 'stale', None
        usable.discard('calculation')
    if measurement:
        if measurement['input_fingerprint'] != fingerprint:
            states['measurement'], margins['measurement'] = 'stale', None
            usable.discard('measurement')
            reasons.append('实测记录对应旧输入')
        elif not measurement['source'] or not measurement['conditions']:
            states['measurement'], margins['measurement'] = 'undefined', None
            usable.discard('measurement')
            reasons.append('实测缺来源或测试条件')
    valid = tuple(margin for margin in margins.values() if margin is not None)
    status = ('review' if 'review' in states.values() else 'pass' if valid else
              'stale' if 'stale' in states.values() else 'undefined')
    pending_reason = None
    if status == 'undefined':
        pending_reason = ('缺限值' if usable else '缺限值和结果') if limit is None else '缺结果'
        if limit is None:
            reasons.append('到器件 BOM 与规格补充额定值或适用降额限值' if criterion['id'].startswith('bom_')
                           else '到对应设计页补充目标或限值')
        if not usable:
            reasons.append('当前工况缺少可比较的计算、仿真或实测结果')
    elif status == 'stale' and stale_calculation:
        reasons.append('需更新旧计算结果')

    def delta(source):
        measurement_value = available[source]
        # A device simulation can include startup and switching spikes,
        # while its calculated value may only describe the blocking platform.
        if (criterion['group'] == 'performance' and value not in (None, 0)
                and measurement_value is not None and states[source] in ('pass', 'review')):
            return 100 * (measurement_value - value) / abs(value)
        return None

    return dict(V_in=_number(vin), **available, **target, states=states, margins=margins,
                margin=min(valid, default=None), delta_simulation=delta('simulation'),
                delta_measurement=delta('measurement'), status=status, pending_reason=pending_reason,
                reason='。'.join(reasons),
                sources=dict(calculation='当前计算快照' if value is not None else '待更新计算快照',
                             simulation=origin, measurement=measurement['source'] if measurement else ''),
                measurement_record=copy.deepcopy(measurement),
                calculation_error=case.get('error') or (case.get('loop_error') if criterion['id'] == 'phase_margin' else None))


def report_snapshot(p, range_result=None, joint_record=None, spice_evidence=None):
    """Pure completed-data projection. Never reads arbitrary paths or runs tools."""
    from config_io import decode_config
    p = decode_config(p)
    if spice_evidence is None and isinstance(range_result, dict):
        spice_evidence = range_result.get('engineering_acceptance_evidence')
    fingerprint = input_fingerprint(p)
    config = normalize(p.get('engineering_acceptance'))
    notes = []
    matched = _matches(_base_spec(range_result), fingerprint)
    calculation_cases = _cases(range_result) if matched else {}
    if range_result is not None and not matched:
        notes.append('输入已变，请刷新计算快照。')
    from power_stage import DEFAULT_PARAMS
    from input_voltage_range import normalize_input_voltage_spec
    parameters = dict(DEFAULT_PARAMS, **p)
    if 'V_in_min' not in p and 'V_in_max' not in p:
        parameters.update(V_in_min=parameters['V_in'], V_in_max=parameters['V_in'])
    parameters = normalize_input_voltage_spec(parameters)
    calculation_checks = {case_id: _check_index(case) for case_id, case in calculation_cases.items()}
    criteria = _acceptance_metrics(parameters, calculation_checks)
    spice, bound, origin = _spice_binding(p, fingerprint, joint_record, spice_evidence, notes)
    simulated = _endpoint_simulations(parameters, spice)
    measurements = {(m['criterion_id'], m['case_id']): m for m in config['measurements']}
    rows = []
    for criterion in criteria:
        row = dict(criterion, cases={})
        for case_id in CASE_IDS:
            case = calculation_cases.get(case_id) or {}
            vin = parameters['V_in_min' if case_id == 'Vinmin' else 'V_in_max']
            row['cases'][case_id] = _case_evidence(
                criterion, case, vin, calculation_checks.get(case_id, {}),
                simulated[case_id].get(criterion['id']), measurements.get((criterion['id'], case_id)),
                fingerprint, origin=origin, stale_calculation=range_result is not None and not matched)
        low, high = (row['cases'][case_id]['limit'] for case_id in CASE_IDS)
        row['limits_vary'] = low != high
        row['limit'] = None if row['limits_vary'] else low
        rows.append(row)
    issues = copy.deepcopy(config['issues'])
    for issue in issues:
        issue['effective_status'] = ('stale' if issue['status'] == 'closed' and issue['input_fingerprint'] != fingerprint else
            'undefined' if issue['status'] == 'closed' and not issue['evidence'] else issue['status'])
    groups = [dict(id=key, title=title, summary=_summary([row for row in rows if row['group'] == key]))
              for key, title in GROUPS]
    summary = _summary(rows)
    summary.update(unresolved_issues=sum(issue['effective_status'] != 'closed' for issue in issues),
                   scope='判定覆盖器件规格和电源外特性，依据所列工况的有效证据。')
    return dict(schema=SCHEMA, version=VERSION, input_fingerprint=fingerprint,
        rows=rows, groups=groups, criteria=copy.deepcopy(criteria), issues=issues, evidence_notes=notes,
        calculation_matched=matched, simulation_matched=bound,
        summary=summary,
        config=config)


def manual_measurement(p, criterion_id, case_id, value, *, source, conditions, evidence_ref='', note='', record_id=None):
    """Bind an explicit user entry to this exact input; no automatic rebinding."""
    return normalize(dict(measurements=[dict(id=record_id or f'{criterion_id}:{case_id}',
        criterion_id=criterion_id, case_id=case_id, value=value, source=source, conditions=conditions,
        evidence_ref=evidence_ref, note=note, input_fingerprint=input_fingerprint(p),
        recorded_at=datetime.now(timezone.utc).isoformat())]))['measurements'][0]
