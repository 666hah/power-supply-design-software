"""Fixed-hardware tolerance analysis with the shared steady-state design engine."""

from collections import defaultdict
from copy import deepcopy
from itertools import product
import math

from analysis_workflows import pin_hardware
from capacitor_banks import bank
from design_engine.calculation import build_snapshot
from engineering_acceptance import input_fingerprint
from input_voltage_range import _cancellation_scope, normalize_input_voltage_spec
from isolated_outputs import output_specs, scale_load
from tolerance_statistics import normalize_variables, sample_variables, summarize_samples

MAX_EVALUATIONS = 2000
SCOPE = ('固定标称选型及补偿，按声明工况计算稳态和适用的环路。规格边界遍历仅覆盖离散角点，'
         '未证明参数区间内的全局极值。统计按每块虚拟硬件跨全部工况的最不利值汇总；'
         '钳位、温升及其他结果沿用当前拓扑模型，未计算启动、温度迭代及量产良率。')


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
    coupling = p.get('coupling_config') or {}
    external_matrix = bool(coupling.get('self_inductances_H') and coupling.get('enabled'))
    if not forward and not (flyback and external_matrix):
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
    add('Rs', '电流采样电阻', 'Ω', q.get('Rs'), positive=q.get('control_mode') == 'Peak Current Mode')
    if not (flyback or forward) and q.get('inductor_design_enabled') is False:
        add('inductor_dcr', '成品电感 DCR', 'Ω', q.get('inductor_dcr'))
    if flyback or forward:
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
    return entries


def _set_path(data, path, value):
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
                or key in ('efficiency', 'phase_margin', 'gain_margin', 'f_sw_max', 'ripple')):
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
    criterion('phase_margin', '最小相位裕度', 'deg', (res.get('loop') or {}).get('min_pm'), 'min',
              (checks.get('phase_margin') or {}).get('limit', snapshot['p'].get('pm_target', 60)-1))
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


def _record(worst, measurements, case):
    for key, value in measurements.items():
        row = worst.get(key)
        if row is None or (value['value'] is not None and
                           (row['value'] is None or (value['limit'] is not None, -_score(value)) >
                            (row['limit'] is not None, -_score(row)))):
            worst[key] = dict(value, case=case if value['value'] is not None else None)


def _hardware_fixed(p, nominal):
    fixed = pin_hardware(p, nominal['res'])
    if (fixed.get('_fixed_inductor') or {}).get('design_enabled') is False:
        # Part identity and ratings stay frozen. DCR is intentionally varied
        # from the analysis copy of the actual input, not the pinned nominal.
        fixed['_fixed_inductor'].pop('inductor_dcr', None)
    # Local bank list is the active authoritative representation, including
    # any old two-capacitor configuration materialized above.
    return _materialize(fixed)


def analyze(p, variables, *, samples=0, seed=1, load_fracs=(.1, .5, 1.),
            load_profiles=None, max_evaluations=MAX_EVALUATIONS, progress=None, cancelled=None):
    """Run hard-limit corners and optionally seeded statistical propagation.

    Each sampled virtual unit contributes one metric extremum across the
    entire selected operating grid. Incomplete units do not provide tails.
    """
    from calculation_scheduler import CalculationCancelled

    base = normalize_input_voltage_spec(p)
    variables = _variables(base, variables)
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 0:
        raise ValueError('蒙特卡洛样本数必须为非负整数')
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**32:
        raise ValueError('随机种子需为 0–4294967295 的整数')
    if not isinstance(max_evaluations, int) or isinstance(max_evaluations, bool) or max_evaluations < 1:
        raise ValueError('求解次数上限必须为正整数')
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
                        snapshot = build_snapshot(_load(q, loads))
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
