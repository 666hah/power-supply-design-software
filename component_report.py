"""Key components and grouped stress checks for Word and Excel."""
from component_management import SOURCE, STATUS, evaluate_components, stress_groups


_GROUP_NOTES = {
    'mos': 'Vds 核查覆盖阻断电压及已计算的尖峰。其余尖峰和脉宽待实测。',
    'diode': '反向电压对比 Vrrm。补测寄生尖峰及外部反接、回灌电压。',
    'capacitor': '电压采用电容端电压包络。纹波按单颗 RMS 电流核查，额定值按实际频率和温度修正。',
    'resistor': '平均功耗对比允许值。脉冲功耗查器件手册。',
}


def _stress_label(check, kind):
    from report_architecture import component_check_label

    ref = check['ref']
    if kind == 'diode':
        if check['value'] is None:
            return ref + ' 反向电压'
        detail = next((text for text in ('含局部换流峰值', '周期模型峰值', '未考虑寄生尖峰')
                       if text in check['note']), '')
        if not detail:
            return ref + ' 反向电压'
        return f'{ref} 反向电压（{detail}）'
    if kind == 'capacitor':
        return ref + (' 电容端电压' if check['metric'] == 'voltage' else ' 纹波电流 RMS')
    return component_check_label(check)


def _reading(number, unit):
    return '—' if number is None else f'{number:.4g} {unit}'


def _conclusion(check):
    if check['state'] != 'undefined':
        return STATUS[check['state']]
    missing = []
    if check['rating'] is None:
        missing.append('额定值')
    if check['value'] is None:
        missing.append('应力')
    if check['factor'] is None:
        missing.append('降额因数')
    return '待补' + '、'.join(missing)


def add_component_report(doc, p, res):
    from docx_layout import _font, paragraph, section, table

    data = evaluate_components(p, res)
    section(doc, '1.4  关键器件与降额')
    paragraph(doc, f"采用《{data['source']}》{data['zone']} 区。允许值等于额定值乘降额因数。{data['note']}", True)
    table(doc, ['位号 / 数量', '用途', '厂家', '型号', '封装'], [
        (row['ref'] + (' / 1' if row['quantity'] else ' / 参考'), row['role'],
         row.get('manufacturer') or '—', row.get('model') or '—', row.get('package') or '—')
        for row in data['rows']], [.9, 2.2, 1.2, 1.7, 1.1])
    for group in stress_groups(data):
        kind, checks = group['kind'], group['checks']
        doc.add_heading(group['title'], 3)
        paragraph(doc, _GROUP_NOTES[kind], True)
        rows = []
        for check in checks:
            unit = check['unit']
            limit = _reading(check['limit'], unit)
            if check['factor'] is not None:
                limit += f" / {check['factor']:.0%}"
            rows.append((_stress_label(check, kind), _reading(check['value'], unit),
                         _reading(check['rating'], unit),
                         '—' if check['utilization'] is None else f"{check['utilization']:.1%}",
                         limit, _conclusion(check)))
        result = table(doc, ['位号 / 检查项', '计算应力', '额定值', '使用率', '允许值 / 因数', '结论'],
                       rows, [2.0, .85, .85, .65, 1.15, 1.6])
        colors = {'pass': '176342', 'review': 'AB2318', 'undefined': '8A5514'}
        for row, check in zip(result.rows[1:], checks):
            for run in row.cells[-1].paragraphs[0].runs:
                _font(run, 9, True, colors.get(check['state'], '444444'))
        sources = dict.fromkeys(check['source'].removeprefix(SOURCE + ' / ') for check in checks)
        paragraph(doc, '规则出处为 ' + '、'.join(sources) + '。', True)

    conditions = {}
    for row in data['rows']:
        detail = '。'.join(filter(None, (row.get('conditions'), row.get('note'))))
        if detail:
            conditions.setdefault(detail, []).append(row['ref'])
    if conditions:
        table(doc, ['位号', '额定条件与备注'],
              [('、'.join(refs), detail) for detail, refs in conditions.items()], [1.5, 5.6])
