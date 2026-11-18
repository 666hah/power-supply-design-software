"""Shared Word and Excel projection for a completed tolerance analysis."""

TITLE = '最坏工况与容差'

_STATES = {
    'review': '需复核',
    'incomplete': '待补计算',
    'within': '已计算点满足',
    'unbounded': '待设限值',
}
_DISTRIBUTIONS = {'bounds': '仅上下限', 'uniform': '均匀', 'triangular': '三角', 'normal': '截断正态'}
_TAIL_STATES = {
    'available': '尾部经验分位',
    'no_data': '待补有效样本',
    'incomplete': '待补未完成样本',
    'insufficient_samples': '待补尾部样本',
}


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


def result_summary(result):
    rows = result['rows']
    reviewed = sum(row.get('status') == 'review' for row in rows)
    pending = sum(row.get('status') in ('incomplete', 'unbounded') for row in rows)
    summary = (f"容差校核 {len(rows)} 项，{reviewed} 项需复核，{pending} 项待补计算或限值。"
               f"共 {result['evaluations']} 次求解，失败 {result['failure_count']} 次。")
    return summary


def report_sections(result):
    """Render only observed bounds and any available statistical estimates."""
    rows = result['rows']
    variables = {v['path']: v for v in result.get('variables') or ()}
    deterministic = []
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
        deterministic.append((name, f'{direction} {limit}' if direction and row.get('limit') is not None else limit,
                              _value(row.get('worst'), unit), _value(row.get('margin'), unit),
                              _operation(case) if case else '—', coverage,
                              _STATES.get(row.get('status'), '待补计算')))
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

    yield ('已扫描最坏值与限值', ('指标', '限值', '最坏值', '余量', '发生工况', '有效 / 计划', '结论'),
           deterministic, (1.35, .85, .85, .85, 1.55, .8, .85))
    if cases:
        combinations = []
        for case in cases.values():
            parameters = []
            for path, actual in (case.get('parameters') or {}).items():
                variable = variables.get(path, {})
                parameters.append(f"{variable.get('label') or path} = {_value(actual, variable.get('unit', ''))}")
            combinations.append((_operation(case), _load_split(case), '\n'.join(parameters) or '标称参数'))
        yield '最坏工况的硬件参数', ('发生工况', '模式与各路负载', '计算采用值'), combinations, (1.65, 1.7, 3.75)
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
    notes = [result.get('scope') or '按所列输入、负载及器件边界计算。',
             '指标有阈值时按限值余量最小选工况。未设限值时按该指标的方向取已计算极值。']
    if result.get('samples'):
        notes.append(f"蒙特卡洛配置 {result['samples']} 个硬件样本，随机种子 {result['seed']}。"
                     '均值 ± 4σ 是样本矩诊断。等效分位取正态分布 ±4σ 对应尾概率处的经验分位。'
                     '超限 / 可比为已完成并可与限值比较的样本计数。')
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
        table(doc, headers, rows, widths)
