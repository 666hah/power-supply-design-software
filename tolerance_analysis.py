"""Fixed-hardware tolerance analysis with the shared steady-state design engine."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from itertools import product
import math
import random

from analysis_workflows import pin_hardware
from capacitor_banks import bank
from design_engine.calculation import build_snapshot
from engineering_acceptance import input_fingerprint
from input_voltage_range import _cancellation_scope, normalize_input_voltage_spec
from isolated_outputs import output_specs, scale_load
from loop_acceptance import MIN_PHASE_MARGIN_DEG
from tolerance_statistics import normalize_variables, sample_variables, summarize_samples

MAX_EVALUATIONS = 2000
SCOPE = ('固定标称选型及补偿，按声明工况计算稳态和适用的环路。规格边界遍历仅覆盖离散角点，'
         '未证明参数区间内的全局极值。统计按每块虚拟硬件跨全部工况的最不利值汇总；'
         '钳位、温升及其他结果沿用当前拓扑模型，未计算启动、温度迭代及量产良率。')
STUDY_GROUPS = ('components', 'external')
STAGED_SCOPE = ('固定标称选型和补偿，按列出的输入电压、各路负载和容差组合求解。'
                '角点结果属于已采用的计算模型与离散工况。负载阶跃使用适用的小信号模型。'
                '蒙特卡洛以每块虚拟硬件跨所列工况的任一超限为事件，未判定样本单列。')
THEORY_SCOPE = ('固定标称选型和补偿，按器件作用选取少量硬件和工况复算。'
                '理论边界仅覆盖列出的子模型。整机结果表示已算候选，含适用的小信号负载阶跃响应。'
                '发现超限后可在统计工况集内进行蒙特卡洛。')


def _number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) else None)


def _materialize(p):
    q = deepcopy(p)
    from cot_settings import active,configuration
    if active(q):q['cot_config']=configuration(q)
    q['input_capacitors'] = bank(q, 'input')
    if p.get('outputs'):
        q['outputs'] = [{key: value for key, value in rail.items() if key != 'id'}
                        for rail in output_specs(q)]
        for rail in q['outputs']:
            rail['output_capacitors'] = bank(rail)
    else:
        q['output_capacitors'] = bank(q)
    state = q.get('tolerance_compensation_state') or q.get('__comp')
    if state and not q.get('tolerance_feedback_divider'):
        from tolerance_feedback import materialize_feedback_divider
        materialize_feedback_divider(q, state)
    return q


def available_variables(p):
    """Tolerances are applied to the active values, in SI, on a private copy."""
    q = _materialize(p)
    entries = []

    def add(path, label, unit, value, *, positive=False, upper=None, signed=False):
        if _number(value) is not None and (signed or value >= 0):
            entries.append(dict(path=path, label=label, unit=unit, nominal=float(value),
                                positive=positive, upper=upper,signed=signed))

    def capacitors(path, label, caps):
        for i, cap in enumerate(caps):
            for key, unit in (('C', 'F'), ('ESR', 'Ω'), ('ESL', 'H')):
                add(f'{path}.{i}.{key}', f'{label}{i+1} {key}', unit, cap[key], positive=key == 'C')

    topology = p['topology']
    from cot_settings import active as cot_active
    cot = cot_active(p)
    forward = topology == 'ACF-FORWARD'
    flyback = topology in ('FLYBACK', 'QR-FLYBACK')
    llc = topology == 'LLC'
    coupling = p.get('coupling_config') or {}
    external_matrix = bool(coupling.get('self_inductances_H') and coupling.get('enabled'))
    if llc:
        for key, label, unit, positive in (
            ('llc_lr','谐振电感 Lr','H',True),('llc_cr','谐振电容 Cr','F',True),
            ('llc_lm','励磁电感 Lm','H',True),('llc_tank_r','谐振腔串联电阻','Ω',False),
            ('llc_rect_r','整流单管串联电阻','Ω',False),('llc_dead_time','桥臂死区','s',False),
            ('llc_qoss','单管有效换流电荷','C',False),
        ):
            add(key,label,unit,q.get(key),positive=positive)
        if p['control_mode']=='Hybrid Hysteretic':
            add('llc_hhc_sense','谐振电容检测增益','V/V',q.get('llc_hhc_sense'),positive=True)
            add('llc_hhc_ramp','滞环补偿斜坡','V/s',q.get('llc_hhc_ramp'),positive=True)
    if not (forward or llc) and not (flyback and external_matrix):
        add('L', '变压器原边励磁电感' if flyback else '功率电感', 'H', q.get('L'), positive=True)
    if forward and not external_matrix:
        add('Lm_forward', '正激原边励磁电感', 'H', q.get('Lm_forward'), positive=True)
    if forward and not q.get('outputs'):
        add('L', '输出滤波电感', 'H', q.get('L'), positive=True)
    if forward:
        add('C_clamp', '有源钳位电容', 'F', q.get('C_clamp'), positive=True)
    add('Rds_on', 'Q1 导通电阻', 'Ω', q.get('Rds_on'))
    if cot:
        add('Rds_aux', '每相低侧 MOS 导通电阻', 'Ω', q.get('Rds_aux'))
        labels=dict(L_scale='L 比例',dcr_scale='DCR 比例',rhigh_scale='高侧 Rds 比例',
                    rlow_scale='低侧 Rds 比例',ton_scale='导通定时比例',sense_gain='采样增益',sense_offset_A='采样偏置')
        for index,row in enumerate(q['cot_config']['phase_parameters']):
            for key,label in labels.items():
                add(f'cot_config.phase_parameters.{index}.{key}',f'第 {index+1} 相独立 {label}',
                    'A' if key=='sense_offset_A' else '',row[key],positive=key!='sense_offset_A',signed=key=='sense_offset_A')
        add('cot_config.phase_limit_A','公共逐相限流阈值','A',q['cot_config']['phase_limit_A'])
    if not llc:
        add('Rs', '电流采样电阻', 'Ω', q.get('Rs'), positive=q.get('control_mode') == 'Peak Current Mode')
    if not (flyback or forward or llc) and q.get('inductor_design_enabled') is False:
        add('inductor_dcr', '成品电感 DCR', 'Ω', q.get('inductor_dcr'))
    if flyback or forward or llc:
        add('Rth_transformer', '变压器至环境热阻', 'K/W', q.get('Rth_transformer'), positive=True)
    if flyback and not coupling.get('enabled'):
        add('K', '标量漏感模型 K', '', q.get('K'), positive=True, upper=1.)
    capacitors('input_capacitors', '输入电容 ', q['input_capacitors'])
    for i, rail in enumerate(q.get('outputs') or [q]):
        path = f'outputs.{i}.' if q.get('outputs') else ''
        label = f'OUT{i+1} '
        capacitors(path+'output_capacitors', label+'电容 ', rail['output_capacitors'])
        if not cot:
            add(path+'Vf_diode', label+'整流二极管 Vf 模型值', 'V', rail.get('Vf_diode'))
        if rail.get('d_out_enable'):
            add(path+'Vf_dout', label+'防反二极管 Vf 模型值', 'V', rail.get('Vf_dout'))
        if forward and path:
            add(path+'L', label+'输出滤波电感', 'H', rail.get('L'), positive=True)
    from tolerance_defaults import extra_variables
    return entries + extra_variables(q)


def _set_path(data, path, value):
    from tolerance_defaults import apply_special_tolerance
    if apply_special_tolerance(data, path, value):
        return
    parts = [int(p) if p.isdecimal() else p for p in path.split('.')]
    for part in parts[:-1]:
        data = data[part]
    data[parts[-1]] = float(value)


def _variables(p, variables):
    available = {v['path']: v for v in available_variables(p)}
    indexed = []
    for row in variables:
        if not isinstance(row, dict):
            raise ValueError('容差配置每项需为参数字典')
        path = row.get('path')
        if path not in available:
            raise ValueError(f'{path} 不属于当前拓扑的可扫参数')
        option = available[path]
        if 'nominal' in row and _number(row['nominal']) != option['nominal']:
            raise ValueError(f'{option["label"]} 的标称值已变化，请重新核对容差上下限')
        indexed.append(dict(row, nominal=option['nominal']))
    normalized = normalize_variables(indexed)
    for v in normalized:
        option = available[v['path']]
        if ((v['low'] < 0 and not option.get('signed')) or (option['positive'] and v['low'] == 0)
                or (option['upper'] is not None and v['high'] > option['upper'])):
            raise ValueError(f'{option["label"]} 的容差下限超出物理取值范围')
        v.update(label=option['label'], unit=option['unit'])
    return normalized


def _conditions(base, load_fracs, load_profiles):
    from mos_manual import distinct_endpoints

    lo, hi = base['V_in_min'], base['V_in_max']
    voltages = [(lo, 'min'), (hi, 'max')] if lo != hi or distinct_endpoints(base) else [(lo, 'min')]
    if hi != lo:
        voltages.insert(1, ((lo+hi)/2, 'min'))
    fractions = [_number(x) for x in load_fracs]
    if any(x is None or not 0 < x <= 1 for x in fractions):
        raise ValueError('负载比例需在 (0, 1] 以内')
    output_count = len(base.get('outputs') or [base])
    profiles = [(f'各路 {x:.4g}×额定负载', (x,)*output_count) for x in sorted(set(fractions))]
    for name, values in (load_profiles or {}).items():
        values = tuple(_number(v) for v in values)
        if len(values) != output_count or any(v is None or not 0 < v <= 1 for v in values):
            raise ValueError(f'{name} 需要为每路填写 (0, 1] 的负载比例')
        profiles.append((str(name), values))
    if not profiles:
        raise ValueError('至少声明一组负载')
    return [(vin, side, name, values) for (vin, side), (name, values) in product(voltages, profiles)]


def _load(q, values):
    if len(set(values)) == 1:
        return scale_load(q, values[0])
    for rail, ratio in zip(q['outputs'], values):
        rail['P_out'] *= ratio
        rail['P_out_min'] = min(rail['P_out_min'], rail['P_out'])
    q['P_out'] = sum(rail['P_out'] for rail in q['outputs'])
    return q


def _measurements(snapshot, criteria):
    res = snapshot['res']
    op = res['op']
    results = {}

    def add(key, name, unit, direction, value, limit, strict=False):
        results[key] = dict(id=key, name=name, unit=unit, direction=direction,
                            value=_number(value), limit=_number(limit), strict=strict)

    checks = {c['id']: c for c in snapshot['checks']}
    for check in checks.values():
        relation = check.get('comparison')
        key = check['id']
        if check['state'] in ('reference', 'na') or relation not in ('<=', '<', '>=', '>'):
            continue
        if not (key.startswith(('bom_', 'OUT', 'B_sat', 'temp_rise', 'inductor_peak', 'inductor_rms','cot_'))
                or key in ('efficiency', 'gain_margin', 'f_sw_max', 'ripple')):
            continue
        if key.endswith('_spike') or check.get('value') is None and check.get('limit') is None:
            continue
        add(key, check['name'], check.get('unit', ''), 'max' if relation[0] == '<' else 'min',
            check.get('value'), check.get('limit'), relation in ('<', '>'))

    def criterion(key, name, unit, value, default_direction, fallback_limit=None):
        row = criteria.get(key, {})
        if row.get('enabled') is False:
            return
        relation = row.get('comparison')
        if relation == 'range':
            add(key+'_low', name+'下限', unit, 'min', value, row.get('lower'))
            add(key+'_high', name+'上限', unit, 'max', value, row.get('upper'))
        else:
            direction = 'min' if relation in ('>=', '>') else 'max' if relation in ('<=', '<') else default_direction
            add(key, name, unit, direction, value, row.get('limit', fallback_limit), relation in ('<', '>'))

    criterion('primary_peak', '电感／原边峰值电流', 'A', op.get('I_L_pk'), 'max')
    vds = _number(op.get('V_sw_max'))
    # Peak and blocking plateau use different approved derating rules. A
    # calculated envelope can use that rule only when it matches its value.
    vds_limit = next((checks[k].get('limit') for k in ('bom_Q1_peak', 'bom_Q1_voltage')
                      if k in checks and vds is not None and
                      _number(checks[k].get('value')) is not None and
                      math.isclose(vds, checks[k]['value'], rel_tol=1e-9)), None)
    criterion('vds_peak', 'Q1 最大模型 Vds', 'V', vds, 'max', vds_limit)
    add('phase_margin', '最小相位裕度', 'deg', 'min', (res.get('loop') or {}).get('min_pm'),
        MIN_PHASE_MARGIN_DEG, strict=True)
    rails = res.get('outputs') or [{'id': 1, 'op': op}]
    for rail in rails:
        tag = f'OUT{rail["id"]}'
        key = tag.lower()+'_voltage'
        voltage = rail['op'].get('V_out')
        if key in criteria:
            criterion(key, tag+' 端口平均电压', 'V', voltage, 'min')
        else:
            add(key+'_low', tag+' 最低端口平均电压', 'V', 'min', voltage, None)
            add(key+'_high', tag+' 最高端口平均电压', 'V', 'max', voltage, None)
    return results


def _score(item):
    """Lower score is less favorable, using the applicable per-case limit."""
    value, limit = item['value'], item['limit']
    if item['direction'] == 'max':
        return limit-value if limit is not None else -value
    return value-limit if limit is not None else value


def _exceeds(item):
    return (item is not None and item['value'] is not None and item['limit'] is not None and
            (_score(item) < 0 or item['strict'] and _score(item) == 0))


def _record(worst, measurements, case):
    for key, value in measurements.items():
        row = worst.get(key)
        if row is None or (value['value'] is not None and
                           (row['value'] is None or (value['limit'] is not None, -_score(value)) >
                            (row['limit'] is not None, -_score(row)))):
            worst[key] = dict(value, case=case if value['value'] is not None else None)


def _hardware_fixed(p, nominal):
    fixed = pin_hardware(p, nominal['res'])
    from cot_settings import active as cot_active

    try:
        if p['topology'] == 'LLC' and not p.get('llc_ki'):
            from llc_model import controller_gains
            op = nominal['op']['llc']
            if not op.get('loop_valid'):
                raise ValueError('标称 LLC 工况不支持环路计算')
            fixed['llc_kp'], fixed['llc_ki'] = controller_gains(p, op)
        elif cot_active(p) and not p.get('cot_ki_hz_per_s'):
            from cot_loop import controller_gains
            fixed['cot_kp_hz'], fixed['cot_ki_hz_per_s'] = controller_gains(p, nominal['op'])
    except (ValueError, ArithmeticError) as exc:
        fixed['_tolerance_loop_error'] = f'无法冻结标称补偿：{exc}'
    if (fixed.get('_fixed_inductor') or {}).get('design_enabled') is False:
        # Part identity and ratings stay frozen. DCR is intentionally varied
        # from the analysis copy of the actual input, not the pinned nominal.
        fixed['_fixed_inductor'].pop('inductor_dcr', None)
    # Local bank list is the active authoritative representation, including
    # any old two-capacitor configuration materialized above.
    return _materialize(fixed)


def _snapshot_at_load(q, loads):
    nominal_error = q.get('_tolerance_loop_error')
    snapshot = build_snapshot(_load(q, loads), include_loop=nominal_error is None)
    if nominal_error:
        snapshot['loop_error'] = nominal_error
    return snapshot


def _validate_run_settings(samples, seed, max_evaluations):
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 0:
        raise ValueError('蒙特卡洛样本数必须为非负整数')
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**32:
        raise ValueError('随机种子需为 0–4294967295 的整数')
    if not isinstance(max_evaluations, int) or isinstance(max_evaluations, bool) or max_evaluations < 1:
        raise ValueError('求解次数上限必须为正整数')


def analyze(p, variables, *, samples=0, seed=1, load_fracs=(.1, .5, 1.),
            load_profiles=None, max_evaluations=MAX_EVALUATIONS, progress=None, cancelled=None,
            staged=False, external_limits=None, retain_plan=False, boundary_strategy='grid'):
    """Run hard-limit corners and optionally seeded statistical propagation.

    Each sampled virtual unit contributes one metric extremum across the
    entire selected operating grid. Incomplete units do not provide tails.
    The staged workflow conditions sampling on an observed hard-limit breach
    and records separate component and external-specification risk.
    The theory-guided strategy screens a small deterministic set instead of
    asking for more corner solves when the numerical budget is raised.
    With retain_plan=True, a boundary-only staged run returns (result, plan).
    """
    from calculation_scheduler import CalculationCancelled

    base = normalize_input_voltage_spec(p)
    variables = _variables(base, variables)
    _validate_run_settings(samples, seed, max_evaluations)
    if retain_plan and (not staged or samples):
        raise ValueError('续算计划只能通过分阶段的极限容差计算生成')
    if boundary_strategy not in ('grid', 'theory_guided') or (boundary_strategy != 'grid' and not staged):
        raise ValueError('理论定向筛查用于分阶段容差计算')
    if staged:
        return _analyze_staged(p, base, variables, samples, seed, load_fracs, load_profiles,
                               max_evaluations, external_limits, progress, cancelled, retain_plan, boundary_strategy)
    if samples and (not variables or any(v['distribution'] == 'bounds' for v in variables)):
        raise ValueError('蒙特卡洛需要为每项已选容差声明分布')
    conditions = _conditions(base, load_fracs, load_profiles)
    center = tuple(v['nominal'] for v in variables)
    active = sum(v['low'] != v['high'] for v in variables)
    center_in_corners = all(v['nominal'] in (v['low'], v['high']) for v in variables)
    deterministic_count = 2**active + int(not center_in_corners)
    total = (deterministic_count+samples)*len(conditions)
    if total > max_evaluations:
        raise ValueError(f'计划需 {total} 次求解，超过上限 {max_evaluations}。请选择影响最大的容差项或减少样本／负载工况。')
    grid = list(product(*(tuple(dict.fromkeys((v['low'], v['high']))) for v in variables)))
    grid = [center] + [values for values in grid if values != center]
    draws = sample_variables(variables, samples, seed) if samples else ()
    criteria = {item.get('metric'): item for item in (base.get('engineering_acceptance') or {}).get('criteria', [])}
    done, failure_count = 0, 0
    worst, coverage, threshold_coverage = {}, defaultdict(int), defaultdict(int)
    results, fault_counts, compared_units = defaultdict(list), defaultdict(int), defaultdict(int)
    failures = []

    with _cancellation_scope(cancelled):
        reference = _materialize(dict(base, V_in=base['V_in_min'], input_voltage_case='min'))
        if progress:
            progress(0, total, '固定标称磁件与绕组')
        nominal = build_snapshot(reference, include_loop=False)
        fixed = _hardware_fixed(reference, nominal)
        for prefix, hardware_units in (('WC', grid), ('MC', draws)):
            for i, values in enumerate(hardware_units, 1):
                unit_values, unit_margins = defaultdict(list), defaultdict(list)
                for j, (voltage, side, profile, loads) in enumerate(conditions, 1):
                    if cancelled and cancelled():
                        raise CalculationCancelled()
                    params = {v['path']: float(value) for v, value in zip(variables, values)}
                    case = dict(id=f'{prefix}-{i:04d}-{j:02d}', voltage=voltage,
                                load_frac=loads[0] if len(set(loads)) == 1 else None,
                                load_profile=profile, load_fractions=list(loads), parameters=params,
                                input_voltage_case=side)
                    q = deepcopy(fixed)
                    q['_skip_cot_transient']=True
                    q.update(V_in=voltage, input_voltage_case=side)
                    for path, value in params.items():
                        _set_path(q, path, value)
                    try:
                        snapshot = _snapshot_at_load(q, loads)
                        measured = _measurements(snapshot, criteria)
                        case['mode'] = snapshot['op'].get('mode')
                        if prefix == 'WC':
                            _record(worst, measured, case)
                            for key, item in measured.items():
                                coverage[key] += item['value'] is not None
                                threshold_coverage[key] += item['value'] is not None and item['limit'] is not None
                        else:
                            for key, item in measured.items():
                                if item['value'] is None:
                                    continue
                                unit_values[key].append(item['value'])
                                if item['limit'] is not None:
                                    margin = _score(item)
                                    unit_margins[key].append(margin < 0 or (margin == 0 and item['strict']))
                    except CalculationCancelled:
                        raise
                    except (ValueError, RuntimeError, ArithmeticError) as exc:
                        failure_count += 1
                        if len(failures) < 50:
                            failures.append(dict(case, error=f'{type(exc).__name__}: {exc}'))
                    done += 1
                    if progress:
                        progress(done, total, case['id'])
                for key, series in unit_values.items():
                    if len(series) == len(conditions) and key in worst:
                        pick = max if worst[key]['direction'] == 'max' else min
                        results[key].append(pick(series))
                        if len(unit_margins[key]) == len(conditions):
                            compared_units[key] += 1
                            fault_counts[key] += any(unit_margins[key])

    rows = []
    expected = deterministic_count*len(conditions)
    for key, row in worst.items():
        value = row.pop('value')
        limit = row['limit']
        margin = _score(dict(row, value=value)) if value is not None and limit is not None else None
        review = margin is not None and (margin < 0 or row['strict'] and margin == 0)
        complete = coverage[key] == expected and threshold_coverage[key] in (0, expected)
        status = 'review' if review else 'incomplete' if not complete else 'unbounded' if limit is None else 'within'
        statistics = summarize_samples(results[key], samples) if samples else None
        if statistics and compared_units[key]:
            statistics.update(observed_exceedances=fault_counts[key], compared_units=compared_units[key])
        rows.append(dict(row, worst=value, margin=margin, status=status, evidence='calculation',
                         evaluated_cases=coverage[key], expected_cases=expected, statistics=statistics))
    order = {'review': 0, 'incomplete': 1, 'unbounded': 2, 'within': 3}
    rows.sort(key=lambda row: order[row['status']])
    return dict(schema='powerdesign-tolerance-1', input_fingerprint=input_fingerprint(p), variables=variables,
                rows=rows, scope=SCOPE, failure_count=failure_count, failures=failures,
                samples=samples, seed=seed, evaluations=done, deterministic_cases=expected,
                conditions=[dict(voltage=v, input_voltage_case=s, load_profile=n, load_fractions=list(ls))
                            for v, s, n, ls in conditions])


def _staged_conditions(base, load_fracs, load_profiles):
    """Add independently varied load endpoints, retaining explicit user cases."""
    conditions = _conditions(base, load_fracs, load_profiles)
    rails = output_specs(base) if base.get('outputs') else [base]
    if not all(r['P_out'] > 0 for r in rails):
        return conditions, False
    rated = (1.,)*len(rails)
    fallback = min(ratio for _, _, _, loads in conditions for ratio in loads)
    light = tuple(min(1., r.get('P_out_min', 0)/r['P_out']) for r in rails)
    no_load = any(ratio <= 0 for ratio in light)
    light = tuple(ratio if ratio > 0 else fallback for ratio in light)
    # Up to three rails retain every mix of their low/rated limits. For larger
    # designs test each output with the others at either extreme, plus split
    # patterns, and report the remaining load combinations as uncovered.
    active = sum(value < 1 for value in light)
    if active <= 3:
        mixes = set(product(*(tuple(dict.fromkeys((lo, hi))) for lo, hi in zip(light, rated))))
    else:
        mixes = {light, rated}
        for i in range(len(rails)):
            mixes.add(tuple(light[n] if n == i else rated[n] for n in range(len(rails))))
            mixes.add(tuple(rated[n] if n == i else light[n] for n in range(len(rails))))
        for parity in range(2):
            mixes.add(tuple(light[i] if i % 2 == parity else rated[i] for i in range(len(rails))))
    seen = {(v, case, loads) for v, case, _, loads in conditions}
    voltages = tuple(dict.fromkeys((v, case) for v, case, _, _ in conditions))
    for voltage, case in voltages:
        for mix in sorted(mixes):
            if (voltage, case, mix) not in seen:
                label = '负载边界 ' + '/'.join(f'{ratio*100:.4g}%' for ratio in mix)
                conditions.append((voltage, case, label, mix))
    unique_loads = {loads for _, _, _, loads in conditions}
    extremes = {loads for loads in unique_loads if all(x in (lo, hi) for x, lo, hi in zip(loads, light, rated))}
    return conditions, len(extremes) == 2**active and not no_load


def _condition_key(case):
    voltage, side, _, loads = case
    return voltage, side, loads


def _theory_schedule(base, fixed, variables, grid, declared, budget):
    """Schedule only useful hardware/operating pairs without a Cartesian sweep."""
    from tolerance_boundary import boundary_candidates, interior_conditions

    candidates, theory_checks = boundary_candidates(fixed, variables)
    interior = interior_conditions(fixed)
    # Prefer the analytic label when the proposed point is already in the grid.
    grid = list({_condition_key(case): case for case in (*grid, *interior)}.values())
    ends = (base['V_in_min'], base['V_in_max'])
    end_cases = [case for case in grid if case[0] in ends]
    rated = max((case[3] for case in grid), key=sum)
    light = min((case[3] for case in grid), key=sum)
    full_cases = [case for case in end_cases if case[3] == rated]
    light_cases = [case for case in end_cases if case[3] == light]
    declared_cases = [case for case in declared if case[0] in ends]
    rated_midpoints = [case for case in grid if case[0] not in ends and case[3] == rated]

    feedback_index = int(base.get('feedback_output', 1)) - 1
    mixed_loads = {tuple(light[i] if (i == feedback_index) == light_feedback else rated[i]
                         for i in range(len(rated))) for light_feedback in (True, False)}
    mixed_cases = [case for case in end_cases if case[3] in mixed_loads]
    proposed = [dict() for _ in candidates]
    selected = [dict() for _ in candidates]
    trials = []

    def propose(index, cases):
        for case in cases:
            key = _condition_key(case)
            if key not in proposed[index]:
                proposed[index][key] = case
                trials.append((index, key, case))

    propose(0, full_cases)
    propose(0, interior)
    propose(0, light_cases)
    for index in range(1, len(candidates)):
        propose(index, full_cases)
    propose(0, declared_cases)
    propose(0, mixed_cases)
    propose(0, rated_midpoints)
    for index in range(1, len(candidates)):
        propose(index, light_cases)

    # Verify internal Buck candidates also with the first power-stage perturbation.
    reactive = [i for i, row in enumerate(variables)
                if row['path'] in ('L', 'inductor_dcr') or 'capacitors.' in row['path']]
    center = candidates[0][1]
    for index, (_, values) in enumerate(candidates[1:], 1):
        if any(values[i] != center[i] for i in reactive):
            propose(index, interior)
            break
    for index, key, case in trials[:budget]:
        selected[index][key] = case
    schedule = [(label, values, list(cases.values())) for (label, values), cases in zip(candidates, selected) if cases]
    return grid, schedule, theory_checks, len(trials)


def _condition_data(conditions):
    return [dict(voltage=v, input_voltage_case=s, load_profile=n, load_fractions=list(loads))
            for v, s, n, loads in conditions]


def _refine_buck_case(observations, conditions):
    """Propose at most one line voltage for the most loaded input capacitor."""
    from tolerance_boundary import refine_buck_ripple_input

    points = defaultdict(list)
    utilization = defaultdict(float)
    for voltage, measurements in observations.items():
        for key, item in measurements.items():
            if not (key.startswith('bom_C_IN') and key.endswith('_ripple')) or item['value'] is None:
                continue
            rms, limit = item['value'], item['limit']
            points[key].append((voltage, rms))
            utilization[key] = max(utilization[key], rms/limit if limit and limit > 0 else 0.)
    eligible = [key for key, values in points.items() if len(values) >= 3]
    if eligible:
        voltage = refine_buck_ripple_input(points[max(eligible, key=utilization.__getitem__)])
        if voltage is not None and all(abs(case[0] - voltage) > 1e-6 or case[3] != (1.,) for case in conditions):
            return voltage, 'min', 'Buck 输入电容 RMS 邻点复核', (1.,)
    return None


def _search_boundary(variables, limit, evaluate, seed):
    """Enumerate affordable grids and otherwise select mixed, metric-driven corners."""
    center = tuple(v['nominal'] for v in variables)
    ends = tuple(tuple(dict.fromkeys((v['low'], v['high']))) for v in variables)
    total = 2**sum(len(pair) == 2 for pair in ends)
    include_center = not all(nominal in pair for nominal, pair in zip(center, ends))
    observations = {}

    def probe(values):
        if len(observations) < limit and values not in observations:
            observations[values] = evaluate(values, len(observations)+1)

    def corner(values):
        return all(value in pair for value, pair in zip(values, ends))

    probe(center)
    if total + include_center <= limit:
        for values in product(*ends):
            probe(values)
        return observations, total, total, 'exhaustive'

    switches = [i for i, pair in enumerate(ends) if len(pair) == 2]
    singletons = {}
    for choose_high in (False, True):
        probe(tuple(pair[-1] if choose_high else pair[0] for pair in ends))
        probe(tuple(pair[-1] if (i % 2 == 0) == choose_high else pair[0] for i, pair in enumerate(ends)))
    # Retain room to verify mixed search even when individually
    # sweeping all variables would exhaust the caller's evaluation budget.
    axis_limit = max(len(observations), int(.60*limit))
    for i in switches:
        if len(observations) >= axis_limit:
            break
        for end in ends[i]:
            values = center[:i] + (end,) + center[i+1:]
            probe(values)
            if values in observations:
                singletons[i, end] = observations[values]

    metrics = dict.fromkeys(key for found in observations.values() for key in found)

    def adverse(row):
        value = None if row is None else row['value']
        return math.inf if value is None else _score(row)

    directed = {}
    for key in metrics:
        best_values = min(observations, key=lambda values: adverse(observations[values].get(key)))
        best_edge = []
        ranked_axes = []
        for i, pair in enumerate(ends):
            if len(pair) == 1:
                best_edge.append(pair[0])
                continue
            low, high = (adverse(singletons.get((i, end), {}).get(key)) for end in pair)
            if low == high:
                end = best_values[i] if best_values[i] in pair else pair[(i+len(directed)) % 2]
            else:
                end = pair[int(high < low)]
            best_edge.append(end)
            if math.isfinite(low) and math.isfinite(high):
                ranked_axes.append((abs(low-high), i))
        directed[key] = tuple(best_edge), tuple(i for _, i in sorted(ranked_axes, reverse=True))

    for edge, _ in directed.values():
        probe(edge)
    # Try flipping the most influential axes at already-explicit adverse
    # corners. Taking sensitivity signs alone can miss coupling interactions.
    for ranks in ((0,), (1,), (0, 1)):
        for key, (_, axes) in directed.items():
            if len(observations) >= limit or len(axes) <= ranks[-1]:
                continue
            best = min((x for x in observations if corner(x)),
                       key=lambda values: adverse(observations[values].get(key)))
            trial = list(best)
            for rank in ranks:
                index = axes[rank]
                low, high = ends[index]
                trial[index] = low if best[index] == high else high
            probe(tuple(trial))

    rng = random.Random(seed)
    target = min(limit, total+include_center)
    best_scores = {key: min(adverse(found.get(key)) for found in observations.values()) for key in metrics}
    no_improvement = 0
    for _ in range(min(18, max(6, 2*len(switches)))):
        if len(observations) >= target or no_improvement >= 4:
            break
        values = tuple(rng.choice(pair) for pair in ends)
        opposite = tuple(pair[-1] if v == pair[0] else pair[0] for v, pair in zip(values, ends))
        improved = False
        for trial in (values, opposite):
            if trial in observations:
                continue
            probe(trial)
            for key, row in observations.get(trial, {}).items():
                score, previous = adverse(row), best_scores.get(key, math.inf)
                if score < previous:
                    best_scores[key] = score
                    improved |= not math.isclose(score, previous, rel_tol=1e-7, abs_tol=1e-14)
        no_improvement = 0 if improved else no_improvement + 1
    covered = sum(corner(values) for values in observations)
    return observations, covered, total, 'metric_guided'


def _boundary_rows(worst, coverage, compared, expected, *, candidates=False):
    rows = []
    for key, item in worst.items():
        value, limit = item['value'], item['limit']
        margin = _score(item) if value is not None and limit is not None else None
        if _exceeds(item):
            status = 'review'
        elif coverage[key] != expected or compared[key] not in (0, expected):
            status = 'incomplete'
        else:
            status = 'unbounded' if limit is None else 'candidate_ok' if candidates else 'within'
        row = dict({k: v for k, v in item.items() if k != 'value'}, worst=value,
                         margin=margin, status=status, evidence='calculation',
                         evaluated_cases=coverage[key], expected_cases=expected, statistics=None)
        if candidates:
            row['coverage'] = 'candidates'
        rows.append(row)
    order = {'review': 0, 'incomplete': 1, 'unbounded': 2, 'within': 3, 'candidate_ok': 3}
    rows.sort(key=lambda row: order[row['status']])
    return rows


def _boundary_groups(rows, all_edges):
    results = {}
    for group in STUDY_GROUPS:
        selected = [row for row in rows if row['group'] == group]
        failed = sum(row['status'] == 'review' for row in selected)
        pending = sum(row['status'] in ('unbounded', 'incomplete') for row in selected)
        status = 'review' if failed else 'incomplete' if not selected or pending or not all_edges else 'within'
        results[group] = dict(status=status, checked=len(selected)-pending, review=failed, pending=pending)
    return results


def _event_status(items, length):
    # A verified failure is determinate even if another case could not be
    # evaluated. A nonfailure requires a complete comparable evidence set.
    if any(_exceeds(item) for item in items):
        return True
    if len(items) == length and all(item is not None and item.get('complete', True) and
                                    item['value'] is not None and item['limit'] is not None for item in items):
        return False
    return None


def _event_statistics(counts, attempted):
    from scipy.stats import beta

    failed, passed = counts[True], counts[False]
    compared = failed+passed
    unknown = attempted-compared
    conditional = failed/compared if compared else None
    interval = None
    if compared:
        lo = 0. if not failed else float(beta.ppf(.025, failed, passed+1))
        hi = 1. if not passed else float(beta.ppf(.975, failed+1, passed))
        interval = [lo, hi]
    # CI applies to comparable units only. Retain the unidentified interval
    # across all attempted units separately when model coverage is partial.
    return dict(exceedances=failed, compared_units=compared, unknown_units=unknown,
                probability=conditional if not unknown else None, conditional_probability=conditional,
                confidence_interval_95=interval if not unknown else None,
                conditional_confidence_interval_95=interval,
                zero_failure_upper_95=-math.expm1(math.log(.05)/compared) if compared and not failed and not unknown else None,
                observed_bounds=[failed/attempted, (failed+unknown)/attempted] if attempted else None)


def _propagate_events(study, variables, seed, planned, rows):
    keys = {row['id']: row['group'] for row in rows}
    expected = len(study.conditions)
    selected = {group: [key for key in keys if keys[key] == group] for group in STUDY_GROUPS}
    metrics, counts = defaultdict(list), defaultdict(lambda: defaultdict(int))
    groups = {group: defaultdict(int) for group in STUDY_GROUPS}
    for index, values in enumerate(sample_variables(variables, planned, seed), 1):
        measured = study.unit(values, 'MC', index)
        unit_states = {}
        for row in rows:
            key = row['id']
            items = [case.get(key) for case in measured]
            known = [item['value'] for item in items if item is not None and item.get('complete', True)
                     and item['value'] is not None]
            if len(known) == expected:
                select = max if row['direction'] == 'max' else min
                metrics[key].append(select(known))
            unit_states[key] = _event_status(items, expected)
            counts[key][unit_states[key]] += 1
        for group, group_keys in selected.items():
            statuses = [unit_states[key] for key in group_keys]
            state = True if any(x is True for x in statuses) else (False if statuses and all(x is False for x in statuses) else None)
            groups[group][state] += 1
    for row in rows:
        key = row['id']
        statistics = summarize_samples(metrics[key], planned)
        risk = _event_statistics(counts[key], planned)
        statistics.update(observed_exceedances=risk['exceedances'], compared_units=risk['compared_units'], risk=risk)
        row['statistics'] = statistics
    return {group: _event_statistics(counts, planned) for group, counts in groups.items()}


class _StagedStudy:
    def __init__(self, fixed, variables, conditions, context, limits, progress, total):
        self.fixed, self.variables, self.conditions = fixed, variables, conditions
        self.context, self.limits = context, limits
        self.progress, self.total = progress, total
        self.worst, self.coverage, self.compared = {}, defaultdict(int), defaultdict(int)
        self.done, self.failure_count, self.failures = 0, 0, []

    def unit(self, values, prefix, unit, *, conditions=None, basis=None, start=1, nominal_ccm=None):
        from calculation_scheduler import CalculationCancelled, check_calculation_cancelled
        from tolerance_metrics import measurements

        local_worst, observations = {}, []
        params = {v['path']: float(value) for v, value in zip(self.variables, values)}
        side_names = ('lower', 'upper', 'nominal')
        deviations = {v['path']: side_names[0 if value < v['nominal'] else 1 if value > v['nominal'] else 2]
                      for v, value in zip(self.variables, values)}
        operating_cases = self.conditions if conditions is None else conditions
        for index, (voltage, side, profile, loads) in enumerate(operating_cases, start):
            check_calculation_cancelled()
            case = dict(id=f'{prefix}-{unit:04d}-{index:02d}', voltage=voltage, load_profile=profile,
                        load_frac=loads[0] if len(set(loads)) == 1 else None, load_fractions=list(loads),
                        input_voltage_case=side, parameters=params)
            if prefix == 'WC':
                case['deviations'] = deviations
                if basis is not None:
                    case['candidate_basis'] = basis
            try:
                q = deepcopy(self.fixed)
                q.update(V_in=voltage, input_voltage_case=side, _skip_cot_transient=True)
                for path, value in params.items():
                    _set_path(q, path, value)
                if q.get('tolerance_feedback_divider'):
                    from tolerance_feedback import apply_feedback_divider
                    apply_feedback_divider(q)
                snapshot = _snapshot_at_load(q, loads)
                measured = measurements(snapshot, self.limits, context=dict(self.context, **case))
                if prefix == 'WC':
                    case['mode'] = snapshot['op'].get('mode')
                    if nominal_ccm is not None and loads == (1.,) and case['mode'] == 'CCM':
                        nominal_ccm[voltage] = measured
                    _record(self.worst, measured, case)
                    _record(local_worst, measured, case)
                    for key, item in measured.items():
                        evaluated = item['value'] is not None and item.get('complete', True)
                        self.coverage[key] += evaluated
                        self.compared[key] += evaluated and item['limit'] is not None
                else:
                    observations.append(measured)
            except CalculationCancelled:
                raise
            except (ValueError, RuntimeError, ArithmeticError) as exc:
                self.failure_count += 1
                if len(self.failures) < 50:
                    self.failures.append(dict(case, error=f'{type(exc).__name__}: {exc}'))
                if prefix == 'MC':
                    observations.append({})
            self.done += 1
            if self.progress:
                self.progress(self.done, self.total, case['id'])
        return local_worst if prefix == 'WC' else observations


@dataclass(frozen=True)
class _BoundaryPlan:
    """Private in-memory continuation with verified limits and nominal hardware."""

    design_identity: tuple
    fixed: dict
    conditions: list
    context: dict
    result: dict


def _design_identity(p, fingerprint):
    # Engineering criteria and the legacy compensation state can affect the
    # study but are excluded from the general-purpose design fingerprint.
    criteria = (p.get('engineering_acceptance') or {}).get('criteria') or []
    compensation = p.get('tolerance_compensation_state') or p.get('__comp')
    return fingerprint, deepcopy(criteria), deepcopy(compensation)


def _distributions_ready(variables):
    return bool(variables) and all(v['distribution'] != 'bounds' for v in variables)


def _run_staged_sampling(study, rows, *, status, samples, seed, capacity):
    statistics = dict(requested_samples=samples, samples=0, seed=seed, evaluations=0,
                      groups={}, budget_limited=False)
    if status == 'within':
        statistics['status'] = 'skipped_within'
    elif status != 'review':
        statistics['status'] = 'blocked_incomplete'
    elif not samples:
        statistics['status'] = 'required_not_run'
    elif not _distributions_ready(study.variables):
        statistics['status'] = 'blocked_distribution'
    elif capacity < 1:
        statistics.update(status='blocked_budget', budget_limited=True)
    else:
        actual = min(samples, capacity)
        start = study.done
        groups = _propagate_events(study, study.variables, seed, actual, rows)
        statistics.update(status='completed', samples=actual, budget_limited=actual < samples,
                          evaluations=study.done - start, groups=groups)
    return statistics


def resume_monte_carlo(p, boundary_result, plan, *, samples, seed, max_evaluations=MAX_EVALUATIONS,
                       progress=None, cancelled=None):
    """Sample a verified boundary run with its frozen hardware and a fresh solve budget.

    Pass the original boundary-only result and its retained plan. The returned
    result merges sample statistics with boundary evidence and counts both runs.
    """
    _validate_run_settings(samples, seed, max_evaluations)
    if not isinstance(plan, _BoundaryPlan) or plan.result != boundary_result:
        raise ValueError('请先计算当前配置的极限容差，再运行蒙特卡洛')
    if plan.design_identity != _design_identity(p, input_fingerprint(p)):
        raise ValueError('设计或补偿输入已变更，请重新计算极限容差')
    status = plan.result['boundary']['status']
    if status != 'review':
        raise ValueError('只有极限容差发现超限时才运行蒙特卡洛')

    result = deepcopy(plan.result)
    capacity = max_evaluations // len(plan.conditions)
    planned = min(samples, capacity) if _distributions_ready(result['variables']) else 0
    total = planned * len(plan.conditions)
    study = _StagedStudy(plan.fixed, result['variables'], plan.conditions,
                         plan.context, result['external_limits'], progress, total)
    with _cancellation_scope(cancelled):
        if progress:
            progress(0, total, '蒙特卡洛抽样')
        statistics = _run_staged_sampling(study, result['rows'], status=status,
                                          samples=samples, seed=seed, capacity=capacity)
        if progress:
            progress(study.done, study.done, '完成蒙特卡洛分析')
    result.update(monte_carlo=statistics, samples=statistics['samples'], seed=seed,
                  evaluations=result['evaluations'] + study.done,
                  failure_count=result['failure_count'] + study.failure_count,
                  failures=(result['failures'] + study.failures)[:50])
    return result


def _analyze_staged(p, base, variables, samples, seed, load_fracs, load_profiles,
                    max_evaluations, limits, progress, cancelled, retain_plan, boundary_strategy):
    from calculation_scheduler import check_calculation_cancelled
    from cot_settings import active as cot_active
    from tolerance_metrics import resolve_external_limits

    limits = resolve_external_limits(base, limits)
    load_fracs = tuple(load_fracs)
    conditions, loads_exhaustive = _staged_conditions(base, load_fracs, load_profiles)
    targeted = boundary_strategy == 'theory_guided'
    capacity = max_evaluations//len(conditions)
    if not targeted and not capacity:
        raise ValueError(f'一套固定硬件需覆盖 {len(conditions)} 个工况，超过计算次数上限 {max_evaluations}。')
    corners = 2**sum(v['low'] != v['high'] for v in variables)
    nominal_inside = int(any(v['nominal'] not in (v['low'], v['high']) for v in variables))
    full = corners + nominal_inside
    reserve = min(samples, capacity//2) if full > capacity and _distributions_ready(variables) else 0
    boundary_limit = min(full, capacity-reserve)
    total = min(capacity, boundary_limit+samples) * len(conditions)
    rails = output_specs(base) if base.get('outputs') else [base]
    context = dict(rated_loads_W=[r['P_out'] for r in rails], rated_voltages_V=[r['V_out'] for r in rails])
    with _cancellation_scope(cancelled):
        check_calculation_cancelled()
        if progress:
            progress(0, 0 if targeted else total, '固定标称磁件与绕组')
        reference = _materialize(dict(base, V_in=base['V_in_min'], input_voltage_case='min'))
        fixed = _hardware_fixed(reference, build_snapshot(reference, include_loop=False))
        if targeted:
            declared = _conditions(base, load_fracs, load_profiles)
            conditions, schedule, theory_checks, planned = _theory_schedule(
                base, fixed, variables, conditions, declared, max_evaluations)
            budgeted = sum(len(cases) for _, _, cases in schedule)
            refine = (budgeted < max_evaluations and fixed['topology'] == 'BUCK' and not cot_active(fixed)
                      and len({case[0] for case in schedule[0][2] if case[3] == (1.,)}) >= 3)
            total = budgeted + int(refine)
            total += min(samples, (max_evaluations-total)//len(conditions))*len(conditions)
            if progress:
                progress(0, total, '按指标安排容差候选工况')
            study = _StagedStudy(fixed, variables, conditions, context, limits, progress, total)
            operating = {}
            for index, (label, values, cases) in enumerate(schedule, 1):
                ccm = {} if refine and index == 1 else None
                study.unit(values, 'WC', index, conditions=cases, basis=label, nominal_ccm=ccm)
                extra = _refine_buck_case(ccm, conditions) if ccm else None
                if extra is not None:
                    study.unit(values, 'WC', index, conditions=(extra,), basis=label, start=len(cases)+1)
                    cases.append(extra)
                    conditions.append(extra)
                    planned += 1
                operating.update((_condition_key(case), case) for case in cases)
            boundary = dict(search='theory_guided', exhaustive=False, load_corners_exhaustive=False,
                            hardware_cases=len(schedule), operating_cases=len(operating),
                            conditions=_condition_data(operating.values()), candidate_planned=planned,
                            candidate_batches=[dict(label=label, cases=len(cases)) for label, _, cases in schedule],
                            theory_checks=theory_checks)
            all_edges = False
        else:
            study = _StagedStudy(fixed, variables, conditions, context, limits, progress, total)
            points, covered, possible, strategy = _search_boundary(
                variables, boundary_limit, lambda values, index: study.unit(values, 'WC', index), seed)
            boundary = dict(exhaustive=covered == possible, load_corners_exhaustive=loads_exhaustive,
                            hardware_cases=len(points), tested_corners=covered, total_corners=possible,
                            search=strategy)
            all_edges = covered == possible and loads_exhaustive
        boundary_cases = study.done
        rows = _boundary_rows(study.worst, study.coverage, study.compared, boundary_cases, candidates=targeted)
        groups = _boundary_groups(rows, all_edges)
        statuses = {item['status'] for item in groups.values()}
        status = 'review' if 'review' in statuses else 'within' if statuses == {'within'} else 'incomplete'
        boundary.update(status=status, seed=seed, groups=groups, evaluations=boundary_cases)
        remaining = (max_evaluations-boundary_cases)//len(conditions)
        study.total = study.done + (min(samples, remaining)*len(conditions)
                                    if status == 'review' and _distributions_ready(variables) else 0)
        statistics = _run_staged_sampling(study, rows, status=status, samples=samples,
                                          seed=seed, capacity=remaining)
        if progress:
            progress(study.done, study.done, '完成容差评估')
    result = dict(schema='powerdesign-tolerance-2', input_fingerprint=input_fingerprint(p), variables=variables,
                  rows=rows, scope=THEORY_SCOPE if targeted else STAGED_SCOPE,
                  failure_count=study.failure_count, failures=study.failures,
                  samples=statistics['samples'], seed=seed, evaluations=study.done, deterministic_cases=boundary_cases,
                  boundary=boundary, monte_carlo=statistics, external_limits=limits,
                  conditions=_condition_data(conditions))
    if retain_plan:
        plan = _BoundaryPlan(_design_identity(p, result['input_fingerprint']),
                             fixed, conditions, context, deepcopy(result))
        return result, plan
    return result
