"""Shared Word and Excel projection for a completed tolerance analysis."""

TITLE = '硬件容差边界与分布评估'
_THEORY_TITLE = '可直接推导的边界'

_STATES = {
    'review': '需复核',
    'incomplete': '待补计算',
    'within': '已计算点满足',
    'candidate_ok': '已算候选满足',
    'unbounded': '待设限值',
}
_DISTRIBUTIONS = {'bounds': '仅上下限', 'uniform': '均匀', 'triangular': '三角', 'normal': '截断正态'}
_TAIL_STATES = {
    'available': '尾部经验分位',
    'no_data': '待补有效样本',
    'incomplete': '待补未完成样本',
    'insufficient_samples': '待补尾部样本',
}
GROUP_NAMES = {'components': '器件超规格', 'external': '电源外特性不达标'}
_BOUNDARY = {'within': '已覆盖的规格边界满足', 'review': '发现超限组合', 'incomplete': '边界覆盖或证据待补'}
_MONTE_CARLO = {'skipped_within': '边界满足，跳过抽样', 'blocked_incomplete': '等待边界完成，尚未启动',
                'required_not_run': '已发现超限，等待运行蒙特卡洛', 'blocked_distribution': '待补器件分布',
                'blocked_budget': '求解预算不足', 'completed': '已完成抽样'}


def _value(value, unit=''):
    if value is None:
        return '—'
    unit = '°' if unit == 'deg' else unit
    return f'{value:.7g}' + (' ' + unit if unit else '')


def _operation(case):
    voltage = _value(case.get('voltage'), 'V')
    load = case.get('load_profile')
    if not load and case.get('load_frac') is not None:
        load = f"负载 {100 * case['load_frac']:g}%"
    return ' · '.join(filter(None, (case.get('id'), voltage, load)))


def _load_split(case):
    loads = case.get('load_fractions') or ()
    values = [f'OUT{i} {100 * load:g}%' for i, load in enumerate(loads, 1)]
    return '\n'.join(filter(None, (case.get('mode'), ' / '.join(values)))) or '—'


def _distribution(variable):
    key = variable.get('distribution') or 'bounds'
    lines = [_DISTRIBUTIONS.get(key, key)]
    if key == 'normal' and variable.get('sigma') is not None:
        lines.append('σ ' + _value(variable['sigma'], variable.get('unit', '')))
    if variable.get('group'):
        lines.append('同组分位 ' + variable['group'])
    return '\n'.join(lines)


def _probability(value):
    return '—' if value is None else f'{100*value:.5g}%'


def theory_summary(result):
    lines = []
    for item in (result.get('boundary') or {}).get('theory_checks') or ():
        low, high = (_value(item.get(key), item.get('unit', '')) for key in ('low', 'high'))
        lines.append(f"{item['label']}　{low} 至 {high} · 理论推导")
        lines.extend(text for text in (item.get('formula'), item.get('scope')) if text)
    return '\n'.join(lines)


def stage_summary(result):
    boundary = result.get('boundary')
    if not boundary:
        return ''
    mc = result.get('monte_carlo') or {}
    status = _BOUNDARY.get(boundary.get('status'), '待核对')
    size = boundary.get('hardware_cases', 0)
    guided = boundary.get('search') == 'theory_guided'
    if guided:
        if boundary.get('status') == 'incomplete':
            status = '区间边界待复核'
        operating_cases = boundary.get('operating_cases', '—')
        lines = [f'极限容差　{status} · 定向复算 · {size} 组器件值 · {operating_cases} 个输入与负载工况',
                 '整机数值和结论对应已算候选。']
    else:
        search = '枚举角点' if boundary.get('exhaustive') else '定向搜索'
        corners = f"器件角点 {boundary.get('tested_corners', '—')} / {boundary.get('total_corners', '—')}"
        lines = [f'极限容差　{status} · {search} · 已查 {size} 组硬件 · {corners}']
        if boundary.get('load_corners_exhaustive') is False:
            lines.append('负载边界有待补工况，统计结果对应已列工况。')
    message = ('已算候选未确认超限' if guided and mc.get('status') == 'blocked_incomplete'
               else _MONTE_CARLO.get(mc.get('status'), '尚未启动'))
    if mc.get('requested_samples'):
        message += f" · 实际 {mc.get('samples', 0)} / 请求 {mc['requested_samples']} 个样本"
    lines.append('蒙特卡洛　' + message)
    for key, item in (mc.get('groups') or {}).items():
        count = item.get('compared_units', 0)
        rate = _probability(item.get('probability'))
        unknown = item.get('unknown_units', 0)
        span = item.get('observed_bounds')
        if unknown and span:
            rate = '观测比例范围 ' + ' 至 '.join(map(_probability, span))
        if item.get('zero_failure_upper_95') is not None:
            rate += ' · 单侧 95% 上限 ' + _probability(item['zero_failure_upper_95'])
        lines.append(f"{GROUP_NAMES.get(key, key)}　{rate} · {item.get('exceedances', 0)} / {count} 可比 · {unknown} 待判定")
    return '\n'.join(lines)


def result_summary(result):
    rows = result['rows']
    reviewed = sum(row.get('status') == 'review' for row in rows)
    pending = sum(row.get('status') in ('incomplete', 'unbounded') for row in rows)
    candidate_ok = sum(row.get('status') == 'candidate_ok' for row in rows)
    matched = f'，{candidate_ok} 项已算候选满足' if candidate_ok else ''
    return (f"评估 {len(rows)} 项指标，{reviewed} 项需复核{matched}，{pending} 项待补计算或限值。"
            f"共 {result['evaluations']} 次求解，失败 {result['failure_count']} 次。")


def _theory_bound(item, side, variables):
    lines = [_value(item.get(side), item.get('unit', ''))]
    for path, value in (item.get(f'{side}_parameters') or {}).items():
        variable = variables.get(path, {})
        lines.append(f"{variable.get('label') or path} = {_value(value, variable.get('unit', ''))}")
    return '\n'.join(lines)


def report_sections(result):
    """Render only observed bounds and any available statistical estimates."""
    rows = result['rows']
    variables = {v['path']: v for v in result.get('variables') or ()}
    boundary = result.get('boundary') or {}
    guided = boundary.get('search') == 'theory_guided'
    deterministic = {}
    moments = []
    quantiles = []
    cases = {}
    operators = {'min': ('≥', '>'), 'max': ('≤', '<')}
    for row in rows:
        name, unit = row['name'], row['unit']
        limit = _value(row.get('limit'), unit)
        direction = operators.get(row.get('direction'), ('', ''))[bool(row.get('strict'))]
        case = row.get('case') or {}
        coverage = (f"{row['evaluated_cases']} / {row['expected_cases']}"
                    if row.get('evaluated_cases') is not None and row.get('expected_cases') is not None else '—')
        deterministic.setdefault(row.get('group'), []).append((
            name, f'{direction} {limit}' if direction and row.get('limit') is not None else limit,
            _value(row.get('worst'), unit), _value(row.get('margin'), unit),
            _operation(case) if case else '—', coverage, _STATES.get(row.get('status'), '待补计算')))
        if case:
            cases.setdefault(case['id'], case)
        stats = row.get('statistics')
        if stats is None:
            continue
        compared = stats.get('compared_units')
        exceedances = f"{stats['observed_exceedances']} / {compared}" if compared else '—'
        moments.append((name, stats['count'], stats.get('missing_count', 0),
                        _value(stats.get('mean'), unit), _value(stats.get('std'), unit),
                        _value(stats.get('moment_4sigma_low'), unit), _value(stats.get('moment_4sigma_high'), unit),
                        exceedances))
        low, high = stats.get('quantile_4sigma_low'), stats.get('quantile_4sigma_high')
        tail = stats.get('expected_tail_count')
        state = _TAIL_STATES.get(stats.get('tail_status'), '待补尾部样本')
        if stats.get('reason'):
            state += '\n' + str(stats['reason'])
        quantiles.append((name, _value(low, unit), _value(high, unit), _value(tail), state))

    monte_carlo = result.get('monte_carlo') or {}
    if monte_carlo.get('groups'):
        probabilities = []
        for key, item in monte_carlo['groups'].items():
            interval = item.get('confidence_interval_95')
            confidence = ' 至 '.join(map(_probability, interval)) if interval else '—'
            probability = _probability(item.get('probability'))
            if item.get('unknown_units') and item.get('observed_bounds'):
                probability = ' 至 '.join(map(_probability, item['observed_bounds']))
            zero_upper = item.get('zero_failure_upper_95')
            if zero_upper is not None:
                confidence += '\n零失效上限 ' + _probability(zero_upper)
            probabilities.append((GROUP_NAMES[key], item.get('exceedances', 0), item.get('compared_units', 0),
                                  item.get('unknown_units', 0), probability, confidence))
        yield ('硬件样本失效概率', ('事件', '失效样本', '可比样本', '待判定', '估计或观测范围', '95% 区间'),
               probabilities, (1.45, .85, .85, .85, 1.4, 1.6))
    if boundary.get('theory_checks'):
        theory = [(item['label'], _theory_bound(item, 'low', variables), _theory_bound(item, 'high', variables),
                   item.get('formula') or '—', item.get('scope') or '—')
                  for item in boundary['theory_checks']]
        yield (_THEORY_TITLE, ('子模型', '理论下限', '理论上限', '计算公式', '适用范围'),
               theory, (1.2, 1.32, 1.32, 1.28, 1.98))
    titles = ({'components': '器件规格候选工况', 'external': '电源外特性候选工况'} if guided
              else {'components': '器件规格边界', 'external': '电源外特性边界'})
    worst_label = '已算最不利值' if guided else '最坏值'
    for group, data in deterministic.items():
        yield (titles.get(group, '已算值与限值'), ('指标', '限值', worst_label, '余量', '发生工况', '有效 / 计划', '结论'),
               data, (1.3, .8, 1., .8, 1.48, .8, .92))
    if cases:
        combinations = []
        for case in cases.values():
            parameters = []
            for path, actual in (case.get('parameters') or {}).items():
                variable = variables.get(path, {})
                side = {'lower': '下偏', 'upper': '上偏', 'nominal': '标称'}.get((case.get('deviations') or {}).get(path))
                parameter = f"{variable.get('label') or path} = {_value(actual, variable.get('unit', ''))}"
                parameters.append(parameter + (f' · {side}' if side else ''))
            operation = '\n'.join(filter(None, (_operation(case), case.get('candidate_basis'))))
            combinations.append((operation, _load_split(case), '\n'.join(parameters) or '标称参数'))
        title = '已算最不利工况的硬件参数' if guided else '最坏工况的硬件参数'
        yield title, ('发生工况', '模式与各路负载', '计算采用值'), combinations, (1.65, 1.7, 3.75)
    if variables:
        inputs = [(v.get('label') or path, _value(v.get('nominal'), v.get('unit', '')),
                   _value(v['low'], v.get('unit', '')), _value(v['high'], v.get('unit', '')),
                   _distribution(v), v.get('source') or '未填分布来源') for path, v in variables.items()]
        yield ('器件容差与分布输入', ('参数', '标称', '下限', '上限', '分布', '来源'),
               inputs, (1.4, .85, .85, .85, 1.3, 1.85))
    if moments:
        yield ('蒙特卡洛样本统计', ('指标', '有效样本', '缺失样本', '均值', '标准差', '均值 − 4σ', '均值 + 4σ', '超限 / 可比'),
               moments, (1.15, .65, .65, .85, .9, .95, .95, 1.1))
        yield ('蒙特卡洛 4σ 等效分位', ('指标', '下尾分位', '上尾分位', '预期每尾样本', '证据状态'),
               quantiles, (1.6, 1, 1, 1.25, 2.25))
    if result.get('failures'):
        failures = [(_operation(item), item.get('error') or item.get('reason') or '求解失败')
                    for item in result['failures']]
        yield '未完成工况记录', ('发生工况', '失败原因'), failures, (2.15, 4.95)


def result_notes(result):
    notes = stage_summary(result).splitlines()
    notes.extend((result.get('scope') or '按所列输入、负载及器件边界计算。',
                  '指标有阈值时按限值余量最小选工况。未设限值时按该指标的方向取已计算极值。'))
    if result.get('samples'):
        notes.append(f"蒙特卡洛配置 {result['samples']} 个硬件样本，随机种子 {result['seed']}。"
                     '均值 ± 4σ 是样本矩诊断。等效分位取正态分布 ±4σ 对应尾概率处的经验分位。'
                     '超限 / 可比为已完成并可与限值比较的样本计数。')
    if (result.get('monte_carlo') or {}).get('groups'):
        notes.append('两类概率分别按样本内任一指标超限计数。证据不全的样本单列待判定。零次观测超限时仍保留统计上限。')
    if result['failure_count'] > len(result.get('failures') or ()):
        notes.append('失败明细仅列已保存的记录。')
    if result.get('input_fingerprint'):
        notes.append(f"计算输入指纹 {result['input_fingerprint']}")
    return notes


def add_word_chapter(doc, result, title=TITLE, *, level=1):
    from docx_layout import paragraph, table
    from report_architecture import module_section

    module_section(doc, title, level=level, new_page=False)
    paragraph(doc, result_summary(result))
    for note in result_notes(result):
        paragraph(doc, note, True)
    for heading, headers, rows, widths in report_sections(result):
        module_section(doc, heading, level=level+1, size=13, new_page=False)
        math_columns = (3,) if heading == _THEORY_TITLE else ()
        table(doc, headers, rows, widths, math_columns=math_columns)
