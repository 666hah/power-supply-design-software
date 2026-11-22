"""Desktop editor and result projection for fixed-hardware tolerance analysis."""

import csv
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config_io import UNITS
from engineering_acceptance import input_fingerprint
from loop_acceptance import MIN_PHASE_MARGIN_DEG
from numeric_input import limit_numeric_input
from scrollable_results import ScrollableResults
from tolerance_report import TITLE as TOLERANCE_TITLE, result_summary, stage_summary, theory_summary


DISTRIBUTIONS = {
    'bounds': '只使用上下限', 'uniform': '均匀分布',
    'triangular': '三角分布', 'normal': '截断正态分布',
}
STATES = {'review': '超限', 'incomplete': '覆盖未完成',
          'within': '已算工况内满足', 'candidate_ok': '已算候选满足', 'unbounded': '待补阈值'}
PROFILE_SCHEMA = 'powerdesign-tolerance-profile-1'
DEFAULT_SAMPLES = 64
DEFAULT_BUDGET = 4000
LIMIT_FIELDS = (('voltage_min', '输出电压下限 / V'), ('voltage_max', '输出电压上限 / V'),
                ('ripple_pp', '纹波 Vpp / V'), ('transient_pp', '动态响应 Vpp / V'))
_UNIT_PREFIXES = {
    'F': ('', 'm', 'u', 'n', 'p'), 'H': ('', 'm', 'u', 'n', 'p'),
    's': ('', 'm', 'u', 'n', 'p'), 'C': ('', 'm', 'u', 'n', 'p'),
    'Ω': ('M', 'k', '', 'm', 'u'), 'V': ('k', '', 'm', 'u'),
    'A': ('k', '', 'm', 'u'), 'V/s': ('M', 'k', '', 'm', 'u'), 'V/V': ('', 'm', 'u'),
}
_TOLERANCE_FIELDS = {'low': '容差下限', 'high': '容差上限', 'sigma': '正态分布 σ'}


def _unit_exponents(unit):
    return {(prefix.replace('u', 'µ') + unit) or '无量纲': Decimal(str(UNITS[prefix])).adjusted()
            for prefix in _UNIT_PREFIXES.get(unit, ('',))}


def _default_input_unit(choices, nominal):
    magnitude = Decimal(str(abs(nominal)))
    power = magnitude.adjusted() if magnitude else 0
    return min(choices, key=lambda unit: (choices[unit] > power, abs(power - choices[unit])))


def _rescale_input(value, exponent, label):
    try:
        converted = Decimal(str(value)).scaleb(exponent)
    except InvalidOperation:
        raise ValueError(f'{label}需要填写完整的数值。') from None
    if not converted.is_finite():
        raise ValueError(f'{label}需要填写有限数值。')
    return converted


def _input_text(value):
    value = value.normalize()
    return format(value, 'f') if -6 <= value.adjusted() <= 8 else str(value)


def _number(value, unit=''):
    if value is None:
        return '—'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return '—'
        return f'{value:.9g}' + (f' {unit}' if unit else '')
    return str(value)


def _numeric(text, label):
    try:
        if isinstance(text, bool):
            raise ValueError
        value = float(text)
    except (TypeError, ValueError):
        raise ValueError(f'{label}需要填写数值。') from None
    if not math.isfinite(value):
        raise ValueError(f'{label}需要填写有限数值。')
    return value


def _profile_variable(row):
    path = row.get('path')
    if not isinstance(path, str) or not path:
        raise ValueError('容差项缺少参数路径。')
    distribution = row.get('distribution', 'bounds')
    if not isinstance(distribution, str) or distribution not in DISTRIBUTIONS:
        raise ValueError(f'{path} 的分布类型不受支持。')
    low, high = (_numeric(row.get(key), path + label) for key, label in
                 (('low', '下限'), ('high', '上限')))
    if low >= high:
        raise ValueError(f'{path} 的容差下限须小于上限。')
    item = dict(path=path, low=low, high=high, distribution=distribution)
    if distribution == 'normal':
        sigma = _numeric(row.get('sigma'), path + '的 σ')
        if sigma <= 0:
            raise ValueError(f'{path} 的 σ 须大于 0。')
        item['sigma'] = sigma
    for key in ('source', 'group'):
        value = row.get(key, '')
        if not isinstance(value, str):
            raise ValueError(f'{path} 的来源和相关组应填写文本。')
        if value.strip():
            item[key] = value.strip()
    return item


def normalize_profile(profile=None):
    """Read old standalone profiles and per-design tolerance metadata."""
    profile = {} if profile is None else profile
    if not isinstance(profile, dict) or profile.get('schema', PROFILE_SCHEMA) != PROFILE_SCHEMA:
        raise ValueError('容差配置格式不受支持。')
    rows = profile.get('variables', [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('容差参数列表格式无效。')
    variables = list(map(_profile_variable, rows))
    if len({row['path'] for row in variables}) != len(variables):
        raise ValueError('配置中有重复的容差参数。')
    options = (profile.get('samples', DEFAULT_SAMPLES), profile.get('seed', 1),
               profile.get('max_evaluations', DEFAULT_BUDGET))
    loads = profile.get('load_fracs', [.1, .5, 1.])
    mixed = profile.get('load_profiles', {})
    automatic = profile.get('automatic_defaults', False)
    limits = profile.get('external_limits', {})
    if (any(type(value) is not int for value in options) or options[0] < 0 or not 0 <= options[1] < 2**32 or options[2] <= 0
            or not isinstance(loads, (list, tuple)) or any(type(x) not in (int, float) or not 0 < x <= 1 for x in loads)
            or len(set(loads)) != len(loads)):
        raise ValueError('样本、种子、计算次数上限或负载范围无效。')
    if (not isinstance(mixed, dict) or any(not isinstance(name, str) or not name.strip() or
            any(c in name for c in '=;；') or not isinstance(values, (list, tuple)) or not values or
            any(type(x) not in (int, float) or not 0 < x <= 1 for x in values)
            for name, values in mixed.items()) or not (loads or mixed)):
        raise ValueError('各路负载组合格式无效。')
    if (type(automatic) is not bool or not isinstance(limits, dict) or
            not isinstance(limits.get('outputs', {}), dict)):
        raise ValueError('默认容差标记或外特性规格格式无效。')
    limit_items = limits.get('outputs', {})
    if any(not isinstance(row, dict) for row in limit_items.values()):
        raise ValueError('各路外特性规格应为对象。')
    for row in limit_items.values():
        for key, value in row.items():
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or
                                      key in ('ripple_pp', 'transient_pp') and value < 0):
                raise ValueError('外特性规格须为有限数字或空值。')
    limits = deepcopy(limits)
    limits.pop('phase_margin', None)
    return dict(schema=PROFILE_SCHEMA, variables=variables, automatic_defaults=automatic,
                samples=options[0], seed=options[1], max_evaluations=options[2],
                load_fracs=list(loads), load_profiles=deepcopy(mixed), external_limits=limits)


def _case_text(case):
    if not case:
        return '—'
    parts = [str(case.get('id') or '')]
    if case.get('voltage') is not None:
        parts.append(_number(case['voltage'], 'V'))
    if case.get('load_profile'):
        parts.append(str(case['load_profile']))
    elif case.get('load_frac') is not None:
        parts.append(_number(case['load_frac'] * 100, '%'))
    return ' · '.join(part for part in parts if part)


class TolerancePanel(ttk.Frame):
    def __init__(self, parent, *, get_spec, start, cancel, make_tree):
        super().__init__(parent)
        self._get_spec, self._start, self._cancel = get_spec, start, cancel
        self.variables, self.catalog = {}, {}
        self.use_default_variables = False
        self.external_limits = {}
        self.result = None
        self.boundary_run = None
        self.fingerprint = None
        self.acceptance = None
        self.compensation = None
        self.running = False
        self.stale = False
        self.status = tk.StringVar(value='待计算 · 核对器件容差和输出规格后，点击「计算极限容差」。')
        self.detail = tk.StringVar(value='选择结果行，查看器件偏差、工况和统计覆盖。')
        self.stage_text = tk.StringVar()
        self.theory_text = tk.StringVar()
        self.samples = tk.StringVar(value=str(DEFAULT_SAMPLES))
        self.seed = tk.StringVar(value='1')
        self.load_percents = tk.StringVar(value='10, 50, 100')
        self.mixed_loads = tk.StringVar()
        self.max_evaluations = tk.StringVar(value=str(DEFAULT_BUDGET))

        self._wrap = []
        self._groups = []
        self._note(self, variable=self.status, style='ResultConclusion.TLabel')
        toolbar = ttk.Frame(self, padding=(6, 4))
        toolbar.pack(fill='x')
        self.run_button, self.mc_button, self.cancel_button = self._buttons(toolbar, (
            ('计算极限容差', self.run), ('运行蒙特卡洛', self.run_monte_carlo), ('取消任务', self._cancel),
        ))
        self.progress_bar = ttk.Progressbar(self, maximum=1)
        self.progress_bar.pack(fill='x', padx=8)
        self.scroll = ScrollableResults(self)
        self.scroll.pack(fill='both', expand=True)
        host = self.scroll.content
        self._note(host, '计算顺序 · 先求理论边界并复算代表工况，再对已发现超限的配置估计失效概率。')

        limits = ttk.LabelFrame(host, text='电源外特性规格', padding=(2, 4))
        limits.pack(fill='x', padx=8, pady=4)
        self.limit_tree = make_tree(limits, ('rail', *(key for key, _ in LIMIT_FIELDS)),
            ('输出', *(label for _, label in LIMIT_FIELDS)), (95, 145, 145, 125, 155), height=3)
        self.limit_tree.bind('<Double-1>', lambda _event: self.edit_limits(), add='+')
        self._note(limits, text=f'最小相位裕度须大于 {MIN_PHASE_MARGIN_DEG:g}°。表中的“—”表示待填产品规格。')
        self.limit_button = ttk.Button(limits, text='编辑选中输出规格…', command=self.edit_limits)
        self.limit_button.pack(anchor='w', padx=6, pady=(1, 4))

        variables = ttk.LabelFrame(host, text='器件容差', padding=(2, 4))
        variables.pack(fill='x', padx=8, pady=4)
        self.param_tree = make_tree(variables, ('name', 'nominal', 'low', 'high', 'dist', 'group', 'source'),
            ('参数', '当前标称值', '下限', '上限', '分布', '相关组', '依据'),
            (200, 115, 105, 105, 130, 100, 180), height=4)
        self.param_tree.bind('<Double-1>', lambda _event: self.edit_variable(), add='+')
        controls = ttk.Frame(variables)
        controls.pack(fill='x', padx=4, pady=(2, 4))
        self.edit_buttons = self._buttons(controls, (
            ('添加参数…', lambda: self.edit_variable(new=True)), ('编辑选中…', self.edit_variable),
            ('删除选中', self.remove_variable), ('载入默认容差', self.use_presets),
            ('保存容差配置…', self.save_profile), ('导入容差配置…', self.import_profile),
        ))

        options = ttk.LabelFrame(host, text='计算设置', padding=6)
        options.pack(fill='x', padx=8, pady=4)
        entries = ttk.Frame(options)
        entries.pack(fill='x')
        settings = [(self.load_percents, '各路同比例负载 / %', 15), (self.samples, '蒙特卡洛样本数', 10),
                    (self.seed, '随机种子', 8), (self.max_evaluations, '每阶段计算次数上限', 10)]
        self.option_inputs = []
        pairs = []
        for var, title, width in settings:
            pair = ttk.Frame(entries, padding=(2, 2))
            ttk.Label(pair, text=title).pack(anchor='w')
            field = ttk.Entry(pair, textvariable=var, width=width)
            field.pack(fill='x')
            self.option_inputs.append(field)
            pairs.append(pair)
            var.trace_add('write', self._settings_changed if var is self.load_percents else self._sampling_changed)
        self._groups.append((entries, pairs))
        ttk.Label(options, text='各路负载组合 / %（可空）').pack(anchor='w', padx=4)
        mixed = ttk.Entry(options, textvariable=self.mixed_loads)
        mixed.pack(fill='x', padx=4, pady=(0, 3))
        self.option_inputs.append(mixed)
        self.mixed_loads.trace_add('write', self._settings_changed)
        self._note(options, '三路示例填写「主路轻载=10/100/100」。多组用分号分隔，各值按 OUT1、OUT2… 顺序。')
        self._note(options, '极限容差只复算所选工况。运行蒙特卡洛时填写正整数样本数。'
                           '默认分布在 ±3σ 截断，可用厂家数据或实测批量数据替换。')
        actions = ttk.Frame(options)
        actions.pack(fill='x')
        self.csv_button, self.json_button = self._buttons(actions, (
            ('导出 CSV…', lambda: self.export_result('csv')), ('导出详细 JSON…', lambda: self.export_result('json')),
        ))
        self.result_anchor = self._note(host, variable=self.stage_text)
        self.theory_note = self._note(host, variable=self.theory_text)
        self.theory_note.pack_forget()

        result = ttk.LabelFrame(host, text='关键结果 · 工况复算与样本分布', padding=(2, 4))
        self.result_frame = result
        result.pack(fill='x', padx=8, pady=4)
        self.result_tree = make_tree(result,
            ('group', 'name', 'limit', 'worst', 'margin', 'case', 'risk', 'state'),
            ('分类', '指标', '限值', '已算最不利值', '余量', '对应工况', '超限 / 可比样本', '判断状态'),
            (108, 190, 105, 145, 90, 195, 145, 125), height=8)
        self.result_tree.bind('<<TreeviewSelect>>', self._selected_result, add='+')
        self._note(result, variable=self.detail)
        for tree in (self.limit_tree, self.param_tree, self.result_tree):
            for column in tree['columns']:
                tree.column(column, stretch=False)
        self.result_tree.tag_configure('incomplete', foreground='#a83232')
        self.result_tree.tag_configure('within', foreground='#197442')
        self.result_tree.tag_configure('candidate_ok', foreground='#315c80')
        self.result_tree.tag_configure('unbounded', foreground='#64748b')
        self.bind('<Configure>', self._reflow, add='+')
        self.bind('<Map>', self._on_map, add='+')
        self._update_buttons()

    def _note(self, parent, text='', variable=None, *, style='TLabel'):
        label = ttk.Label(parent, text=text, textvariable=variable, wraplength=780,
                          style=style, justify='left', padding=(6, 3))
        label.pack(fill='x')
        self._wrap.append(label)
        return label

    def _buttons(self, parent, choices):
        widgets = [ttk.Button(parent, text=text, command=action) for text, action in choices]
        self._groups.append((parent, widgets))
        return widgets

    def _reflow(self, _event=None):
        width = max(180, self.winfo_width() - 48)
        for label in self._wrap:
            if int(label.cget('wraplength')) != width:
                label.configure(wraplength=width)
        for _, widgets in self._groups:
            row = col = occupied = 0
            for widget in widgets:
                wanted = widget.winfo_reqwidth() + 8
                if col and occupied + wanted > width:
                    row, col, occupied = row + 1, 0, 0
                info = widget.grid_info()
                if (info.get('row'), info.get('column')) != (row, col):
                    widget.grid(row=row, column=col, sticky='w', padx=3, pady=3)
                col += 1
                occupied += wanted

    def _on_map(self, _event=None):
        # Refresh selectable variables when the page becomes visible. Running
        # the solver always takes a fresh snapshot of both design and profile.
        try:
            self._refresh_catalog()
        except (ValueError, KeyError, TypeError, tk.TclError):
            pass

    def _refresh_catalog(self):
        from tolerance_analysis import available_variables

        spec = self._get_spec()
        self.catalog = {row['path']: row for row in available_variables(spec)}
        if self.use_default_variables:
            from tolerance_defaults import default_variables
            self.variables = {row['path']: row for row in default_variables(spec)}
        self._render_variables()
        self._render_limits(spec)

    def _render_limits(self, spec):
        from tolerance_metrics import resolve_external_limits

        effective = resolve_external_limits(spec, self.external_limits)
        selected = self.limit_tree.selection()
        self.limit_tree.delete(*self.limit_tree.get_children())
        for index, row in effective['outputs'].items():
            self.limit_tree.insert('', 'end', iid=str(index), values=(
                f'OUT{index}', *(_number(row.get(key), 'V') for key, _ in LIMIT_FIELDS)))
        ids = self.limit_tree.get_children()
        if ids:
            self.limit_tree.selection_set(selected[0] if selected and selected[0] in ids else ids[0])

    def edit_limits(self):
        from tolerance_metrics import resolve_external_limits

        if self.running:
            return
        try:
            spec = self._get_spec()
            current = resolve_external_limits(spec, self.external_limits)
        except (TypeError, ValueError, KeyError, tk.TclError) as error:
            messagebox.showerror('电源外特性规格', str(error), parent=self)
            return
        picked = self.limit_tree.selection()
        if not picked:
            return
        index = picked[0]
        dialog = tk.Toplevel(self)
        dialog.title(f'OUT{index} 外特性规格')
        dialog.transient(self.winfo_toplevel())
        dialog.columnconfigure(1, weight=1)
        values = current['outputs'][index]
        fields = {}
        initial = {}
        for row, (key, label) in enumerate(LIMIT_FIELDS):
            value = values.get(key)
            initial[key] = '' if value is None else f'{value:.12g}'
            text = fields[key] = tk.StringVar(master=dialog, value=initial[key])
            ttk.Label(dialog, text=label).grid(row=row, column=0, padx=10, pady=4, sticky='w')
            ttk.Entry(dialog, textvariable=text, width=18).grid(row=row, column=1, padx=10, pady=4, sticky='ew')
        ttk.Label(dialog, text='留空表示待填。反相输出的电压上下限使用有符号电压。'
                               '动态响应按 10%↔90% 负载阶跃的峰峰值检查。',
                  wraplength=390, justify='left').grid(row=len(fields), columnspan=2, sticky='w', padx=10, pady=6)

        def apply():
            try:
                override = {key: _numeric(var.get(), key) if var.get().strip() else None
                            for key, var in fields.items() if var.get().strip() != initial[key]}
                updates = deepcopy(self.external_limits)
                if override:
                    updates.setdefault('outputs', {}).setdefault(index, {}).update(override)
                resolve_external_limits(spec, updates)
            except (TypeError, ValueError) as error:
                messagebox.showerror('电源外特性规格', str(error), parent=dialog)
                return
            self.external_limits = updates
            self._render_limits(spec)
            self._clear_result('外特性规格已更新。')
            dialog.destroy()

        actions = ttk.Frame(dialog)
        actions.grid(row=len(fields)+1, columnspan=2, sticky='e', padx=10, pady=8)
        ttk.Button(actions, text='取消', command=dialog.destroy).pack(side='left', padx=3)
        ttk.Button(actions, text='应用', command=apply).pack(side='left', padx=3)
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.grab_set()

    def use_presets(self):
        previous = self.use_default_variables
        self.use_default_variables = True
        try:
            self._refresh_catalog()
        except (TypeError, ValueError, KeyError, tk.TclError) as error:
            self.use_default_variables = previous
            messagebox.showerror('默认容差', str(error), parent=self)
            return
        self._clear_result('已按当前标称值载入 ±3σ 默认容差。')

    def _render_variables(self):
        selected = self.param_tree.selection()
        self.param_tree.delete(*self.param_tree.get_children())
        for path, row in self.variables.items():
            item = self.catalog.get(path, {})
            unit = item.get('unit') or ''
            distribution = DISTRIBUTIONS[row['distribution']]
            if row.get('sigma') is not None:
                distribution += ' · σ ' + _number(row['sigma'], unit)
            self.param_tree.insert('', 'end', iid=path, values=(item.get('label', path),
                _number(item.get('nominal'), unit), _number(row['low'], unit), _number(row['high'], unit),
                distribution, row.get('group', ''), row.get('source', '未注明')), tags=(() if item else ('undefined',)))
        if selected and selected[0] in self.variables:
            self.param_tree.selection_set(selected[0])

    def _budget(self):
        try:
            capacity = int(self.max_evaluations.get())
        except ValueError:
            raise ValueError('每阶段计算次数上限需要填写整数。') from None
        if capacity <= 0:
            raise ValueError('每阶段计算次数上限须大于 0。')
        return capacity

    def _sampling_settings(self):
        try:
            samples, seed = int(self.samples.get()), int(self.seed.get())
        except ValueError:
            raise ValueError('样本数和随机种子需要填写整数。') from None
        if samples < 0 or not 0 <= seed < 2**32:
            raise ValueError('样本数不得为负，随机种子需在 0–4294967295 内。')
        return dict(samples=samples, seed=seed, max_evaluations=self._budget())

    def _settings(self, *, boundary_only=False):
        def load_fractions(text, sep):
            values = [_numeric(part.strip(), '负载百分比') / 100 for part in text.split(sep)]
            if any(not 0 < value <= 1 for value in values):
                raise ValueError('负载百分比须大于 0，且不超过 100。')
            return values

        loads = self.load_percents.get().strip().replace('，', ',')
        numeric = load_fractions(loads, ',') if loads else []
        if len(set(numeric)) != len(numeric):
            raise ValueError('统一负载百分比不能重复。')
        profiles = {}
        mixed = self.mixed_loads.get().strip().replace('；', ';')
        if mixed:
            for group in mixed.split(';'):
                name, sep, values = group.partition('=')
                name = name.strip()
                if not sep or not name or name in profiles:
                    raise ValueError('各路负载按「组名=百分比/百分比」填写，组名不能重复。')
                profiles[name] = load_fractions(values, '/')
        if not (numeric or profiles):
            raise ValueError('至少填写一组负载。')
        sampling = (dict(samples=0, seed=1, max_evaluations=self._budget()) if boundary_only
                    else self._sampling_settings())
        return dict(load_fracs=tuple(numeric), load_profiles=profiles, **sampling)

    def _settings_changed(self, *_args):
        if self.result is not None:
            self._clear_result('负载工况已变化，请重新计算极限容差。')

    def _sampling_changed(self, *_args):
        if self.boundary_run is not None and self.result is not self.boundary_run[0]:
            self._show_result(self.boundary_run[0])
            self._update_buttons()

    def invalidate(self, spec):
        if self.fingerprint is None:
            return
        try:
            unchanged = (spec is not None and input_fingerprint(spec) == self.fingerprint
                         and (spec.get('engineering_acceptance') or {}) == self.acceptance
                         and ('__comp' not in spec or spec['__comp'] == self.compensation))
        except (ValueError, TypeError, KeyError):
            unchanged = False
        if not unchanged and not self.stale:
            self.stale = True
            if self.running:
                self._cancel()
            self._clear_result('当前设计参数已变化，请重新运行。')

    def _clear_result(self, status):
        self.result = None
        self.boundary_run = None
        self.status.set(status)
        self.detail.set('选中结果行可查看已算工况及统计覆盖。')
        self.stage_text.set('')
        self.theory_text.set('')
        self.theory_note.pack_forget()
        self.result_tree.delete(*self.result_tree.get_children())
        self._update_buttons()

    def _update_buttons(self):
        for widget in (*self.edit_buttons, *self.option_inputs, self.run_button, self.limit_button):
            widget.state(('disabled',) if self.running else ('!disabled',))
        self.cancel_button.state(('!disabled',) if self.running and not self.stale else ('disabled',))
        can_sample = not self.running and self._can_sample()
        self.mc_button.state(('!disabled',) if can_sample else ('disabled',))
        self.run_button.configure(style='TButton' if can_sample else 'Accent.TButton')
        self.mc_button.configure(style='Accent.TButton' if can_sample else 'TButton')
        for widget in (self.csv_button, self.json_button):
            widget.state(('!disabled',) if not self.running and self.result is not None else ('disabled',))

    def _can_sample(self):
        if self.boundary_run is None:
            return False
        result, plan = self.boundary_run
        return plan is not None and result['boundary']['status'] == 'review'

    def edit_variable(self, new=False):
        if self.running:
            return
        picked = self.param_tree.selection()
        previous = picked[0] if picked and not new else None
        if not new and previous is None:
            self.status.set('请先选择要编辑的容差项。')
            return
        try:
            self._refresh_catalog()
        except (ValueError, KeyError, TypeError, tk.TclError) as error:
            messagebox.showerror('器件容差', str(error), parent=self)
            return
        choices = {f"{row['label']}  ·  {path}": path for path, row in self.catalog.items() if
                   path not in self.variables or path == previous}
        if previous and previous not in choices.values():
            self.status.set('该参数不适用于当前设计，请删除这一项后重新选择。')
            return
        if not choices:
            self.status.set('没有其他可添加的参数。')
            return
        saved = self.variables.get(previous, {})
        dialog = tk.Toplevel(self)
        dialog.title('器件容差')
        dialog.transient(self.winfo_toplevel())
        dialog.columnconfigure(1, weight=1)
        fields = {key: tk.StringVar(master=dialog, value=saved.get(key, ''))
                  for key in (*_TOLERANCE_FIELDS, 'source', 'group')}
        dist = tk.StringVar(master=dialog, value=DISTRIBUTIONS[saved.get('distribution', 'bounds')])
        selected = tk.StringVar(master=dialog, value=next((name for name, path in choices.items() if path == previous), next(iter(choices))))
        nominal = tk.StringVar(master=dialog)
        unit_var = tk.StringVar(master=dialog)
        unit_choices = {}
        active_unit = active_path = None
        drafts = {}
        ttk.Label(dialog, text='器件参数').grid(row=0, column=0, sticky='w', padx=10, pady=5)
        ttk.Combobox(dialog, textvariable=selected, values=tuple(choices), state='readonly', width=45).grid(
            row=0, column=1, columnspan=2, sticky='ew', padx=10, pady=5)
        ttk.Label(dialog, textvariable=nominal).grid(row=1, column=0, columnspan=3, sticky='w', padx=10, pady=4)
        ttk.Label(dialog, text='输入单位').grid(row=2, column=0, sticky='w', padx=10, pady=4)
        unit_box = ttk.Combobox(dialog, textvariable=unit_var, width=12, state='readonly')
        unit_box.grid(row=2, column=1, sticky='w', padx=10, pady=4)
        entries = {}
        for index, (key, title) in enumerate((*_TOLERANCE_FIELDS.items(),
                     ('source', '依据／来源'), ('group', '相关组（可空）')), 3):
            ttk.Label(dialog, text=title).grid(row=index, column=0, sticky='w', padx=10, pady=4)
            entries[key] = ttk.Entry(dialog, textvariable=fields[key])
            if key in _TOLERANCE_FIELDS:
                limit_numeric_input(entries[key])
            entries[key].grid(row=index, column=1, columnspan=1 if key == 'sigma' else 2,
                              sticky='ew', padx=10, pady=4)
        ttk.Label(dialog, text='分布').grid(row=8, column=0, sticky='w', padx=10, pady=4)
        ttk.Combobox(dialog, textvariable=dist, values=tuple(DISTRIBUTIONS.values()), state='readonly').grid(
            row=8, column=1, columnspan=2, sticky='ew', padx=10, pady=4)
        ttk.Label(dialog, text='同名相关组共用抽样分位。三角分布以标称值为众数。默认预填将规格半宽定义为 3σ。',
                  wraplength=510).grid(row=9, column=0, columnspan=3, sticky='w', padx=10, pady=6)

        def display_nominal():
            center = self.catalog[active_path]['nominal']
            exponent = unit_choices[active_unit]
            nominal.set('标称值 ' + _number(float(Decimal(str(center)).scaleb(-exponent)), active_unit))

        def select_parameter(*_):
            nonlocal active_path, active_unit, unit_choices
            path = choices[selected.get()]
            if path == active_path:
                return
            if active_path is not None:
                drafts[active_path] = (active_unit, {key: fields[key].get() for key in _TOLERANCE_FIELDS})
            active_path = path
            item = self.catalog[path]
            unit_choices = _unit_exponents(item.get('unit') or '')
            if path in drafts:
                active_unit, values = drafts[path]
            else:
                active_unit = _default_input_unit(unit_choices, item['nominal'])
                values = {key: _input_text(Decimal(str(saved[key])).scaleb(-unit_choices[active_unit]))
                          for key in _TOLERANCE_FIELDS if path == previous and key in saved}
            unit_box.configure(values=tuple(unit_choices), state='readonly' if len(unit_choices) > 1 else 'disabled')
            unit_var.set(active_unit)
            for key in _TOLERANCE_FIELDS:
                fields[key].set(values.get(key, ''))
            display_nominal()

        def select_unit(_event):
            nonlocal active_unit
            requested = unit_var.get()
            if requested == active_unit or requested not in unit_choices:
                return
            exponent = unit_choices[active_unit] - unit_choices[requested]
            try:
                values = {key: _input_text(_rescale_input(fields[key].get(), exponent, label))
                          for key, label in _TOLERANCE_FIELDS.items() if fields[key].get().strip()}
            except ValueError as error:
                unit_var.set(active_unit)
                messagebox.showerror('切换输入单位', str(error), parent=dialog)
                return
            active_unit = requested
            for key, value in values.items():
                fields[key].set(value)
            display_nominal()

        def value_in_si(key):
            converted = _rescale_input(fields[key].get(), unit_choices[active_unit], _TOLERANCE_FIELDS[key])
            value = float(converted)
            if not math.isfinite(value) or (value == 0 and converted):
                raise ValueError(f'{_TOLERANCE_FIELDS[key]}超出可表示范围。')
            return value

        def sigma_from_bounds():
            try:
                low, high = (value_in_si(key) for key in ('low', 'high'))
                center = self.catalog[active_path]['nominal']
                if low >= high or not math.isclose(center-low, high-center, rel_tol=1e-7):
                    raise ValueError('按 3σ 换算需要上下限关于标称值对称。')
            except ValueError as error:
                messagebox.showerror('换算 σ', str(error), parent=dialog)
                return
            sigma = (Decimal(str(high)) - Decimal(str(low))) / 6
            fields['sigma'].set(f'{sigma.scaleb(-unit_choices[active_unit]):.17g}')

        sigma_button = ttk.Button(dialog, text='按 ±3σ 换算', command=sigma_from_bounds)
        sigma_button.grid(row=5, column=2, sticky='e', padx=(0, 10), pady=4)

        def refresh_distribution(*_):
            state = ('!disabled',) if dist.get() == DISTRIBUTIONS['normal'] else ('disabled',)
            entries['sigma'].state(state)
            sigma_button.state(state)

        def apply():
            path = active_path
            distribution = next(key for key, label in DISTRIBUTIONS.items() if label == dist.get())
            try:
                values = {key: value_in_si(key) for key in ('low', 'high')}
                if distribution == 'normal':
                    values['sigma'] = value_in_si('sigma')
                row = _profile_variable(dict(path=path, distribution=distribution, **values,
                                             source=fields['source'].get(), group=fields['group'].get()))
                if not row['low'] <= self.catalog[path]['nominal'] <= row['high']:
                    raise ValueError('标称值须在容差上下限内。')
            except (KeyError, ValueError) as error:
                messagebox.showerror('器件容差', str(error), parent=dialog)
                return
            if previous is not None and path != previous:
                del self.variables[previous]
            self.use_default_variables = False
            self.variables[path] = row
            self._render_variables()
            self.param_tree.selection_set(path)
            self._clear_result('容差配置已更新。可运行评估或保存配置。')
            dialog.destroy()

        selected.trace_add('write', select_parameter)
        dist.trace_add('write', refresh_distribution)
        unit_box.bind('<<ComboboxSelected>>', select_unit)
        select_parameter()
        refresh_distribution()
        actions = ttk.Frame(dialog)
        actions.grid(row=10, column=0, columnspan=3, sticky='e', padx=10, pady=10)
        ttk.Button(actions, text='取消', command=dialog.destroy).pack(side='left', padx=4)
        ttk.Button(actions, text='应用', command=apply).pack(side='left', padx=4)
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.grab_set()

    def remove_variable(self):
        if not self.param_tree.selection():
            return
        self.use_default_variables = False
        for path in self.param_tree.selection():
            self.variables.pop(path, None)
        self._render_variables()
        self._clear_result('容差配置已更新。')

    def save_profile(self):
        try:
            profile = self.project_profile()
            path = filedialog.asksaveasfilename(parent=self, defaultextension='.json',
                filetypes=[('容差配置', '*.json')], initialfile='器件容差配置.json')
            if path:
                self._save_json(path, profile)
                self.status.set('容差配置已保存。')
        except (ValueError, OSError) as error:
            messagebox.showerror('保存容差配置', str(error), parent=self)

    def import_profile(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('容差配置', '*.json')])
        if not path:
            return
        try:
            profile = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(profile, dict) or profile.get('schema') != PROFILE_SCHEMA:
                raise ValueError('该 JSON 不是受支持的器件容差配置。')
            from tolerance_metrics import resolve_external_limits
            profile = normalize_profile(profile)
            resolve_external_limits(self._get_spec(), profile['external_limits'])
            self.load_project_profile(profile)
            self._refresh_catalog()
        except (KeyError, OSError, TypeError, ValueError, tk.TclError) as error:
            messagebox.showerror('导入容差配置', str(error), parent=self)
            return
        self._clear_result('容差配置已导入。请核对当前标称值并运行。')

    def project_profile(self):
        return dict(schema=PROFILE_SCHEMA, automatic_defaults=self.use_default_variables,
                    variables=[] if self.use_default_variables else list(self.variables.values()),
                    external_limits=deepcopy(self.external_limits), **self._settings())

    def load_project_profile(self, profile):
        if self.running:
            self.stale = True
            self._cancel()
        self.fingerprint = self.acceptance = self.compensation = None
        self.use_default_variables = profile['automatic_defaults']
        self.variables = {row['path']: dict(row) for row in profile['variables']}
        self.external_limits = deepcopy(profile['external_limits'])
        loads, mixed = profile['load_fracs'], profile['load_profiles']
        self.load_percents.set(', '.join(f'{value*100:g}' for value in loads))
        self.mixed_loads.set('; '.join(name+'='+'/'.join(f'{value*100:g}' for value in values)
                                     for name, values in mixed.items()))
        for variable, key in ((self.samples, 'samples'), (self.seed, 'seed'),
                              (self.max_evaluations, 'max_evaluations')):
            variable.set(str(profile[key]))
        self.catalog = {}
        self._render_variables()
        self._clear_result('核对器件容差和各路输出规格，再计算极限容差。')
        if self.winfo_ismapped():
            self._on_map()

    def run(self):
        try:
            self._refresh_catalog()
            if not self.variables:
                raise ValueError('请至少添加一项器件容差。')
            settings = self._settings(boundary_only=True)
            variables = [dict(row) for row in self.variables.values()]
            for row in variables:
                item = self.catalog.get(row['path'])
                if not item:
                    raise ValueError(f"{row['path']} 不适用于当前设计。")
                if not row['low'] <= item['nominal'] <= row['high']:
                    raise ValueError(f"{item['label']} 的当前标称值不在所填容差范围内。")
            spec = self._get_spec()
            output_count = len(spec.get('outputs') or [spec])
            for name, values in settings['load_profiles'].items():
                if len(values) != output_count:
                    raise ValueError(f'{name} 应为当前设计的 {output_count} 路输出各填写一个比例。')
            self._start(spec, variables, dict(settings, staged=True, boundary_strategy='theory_guided',
                                              external_limits=deepcopy(self.external_limits)))
        except (KeyError, TypeError, ValueError, tk.TclError) as error:
            messagebox.showerror(TOLERANCE_TITLE, str(error), parent=self)

    def run_monte_carlo(self):
        try:
            spec = self._get_spec()
            self.invalidate(spec)
            if not self._can_sample():
                return
            settings = self._sampling_settings()
            if settings['samples'] == 0:
                raise ValueError('运行蒙特卡洛时，样本数须大于 0。')
            self._start(spec, (), settings, boundary_run=self.boundary_run)
        except (KeyError, TypeError, ValueError, tk.TclError) as error:
            messagebox.showerror(TOLERANCE_TITLE, str(error), parent=self)

    def started(self, spec, *, sampling):
        self.fingerprint = input_fingerprint(spec)
        self.acceptance = deepcopy(spec.get('engineering_acceptance') or {})
        self.compensation = deepcopy(spec.get('__comp'))
        self.stale = False
        self.running = True
        self.progress_bar.configure(value=0, maximum=1)
        if sampling:
            self.status.set('正在按器件分布准备蒙特卡洛样本…')
            self._update_buttons()
        else:
            self._clear_result('正在准备固定硬件及器件容差工况…')

    def progress(self, done, total, label):
        if not self.stale:
            self.progress_bar.configure(maximum=max(1, total), value=done)
            self.status.set(f'正在计算 {label} · {done}/{total}')

    def finished(self, *, result=None, boundary_run=None, error=None, cancelled=False):
        self.running = False
        if self.stale:
            self._clear_result('当前设计参数已变化，请重新运行。')
        elif cancelled:
            self.status.set('任务已取消。')
        elif error is not None:
            self.status.set(error)
            messagebox.showerror(TOLERANCE_TITLE, error, parent=self)
        else:
            if boundary_run is not None:
                self.boundary_run = boundary_run
            self._show_result(result)
            self.after_idle(self._scroll_to_results)
        self._update_buttons()

    def _scroll_to_results(self):
        if self.result is not None and self.winfo_viewable():
            self.scroll.sync()
            height = self.scroll.content.winfo_reqheight()
            self.scroll.canvas.yview_moveto(self.result_anchor.winfo_y() / max(1, height))

    @staticmethod
    def _statistics_text(row):
        stats = row.get('statistics') or {}
        low, high = (stats.get('quantile_4sigma_low'), stats.get('quantile_4sigma_high'))
        if low is None or high is None:
            return {'incomplete': '有效样本不完整', 'insufficient_samples': '尾部样本不足',
                    'no_data': '无有效样本'}.get(stats.get('tail_status'), '—')
        return f"{_number(low)} 至 {_number(high)} {row.get('unit', '')}".rstrip()

    def _result_values(self, row):
        case = row.get('case')
        unit = row.get('unit', '')
        limit = row.get('limit')
        relation = ({'min': '>', 'max': '<'} if row.get('strict') else {'min': '≥', 'max': '≤'}).get(row.get('direction'), '')
        stats = row.get('statistics') or {}
        count = stats.get('compared_units', 0)
        risk = f"{stats.get('observed_exceedances', 0)} / {count}" if count else '—'
        names = {'components': '器件规格', 'external': '电源外特性'}
        return (names.get(row.get('group'), '—'), row['name'],
                f'{relation} {_number(limit, unit)}'.strip() if limit is not None else '—',
                _number(row.get('worst'), unit), _number(row.get('margin'), unit), _case_text(case),
                risk, STATES.get(row.get('status'), '待复核'))

    def _show_result(self, result):
        self.result = result
        self.result_tree.delete(*self.result_tree.get_children())
        for index, row in enumerate(result['rows']):
            self.result_tree.insert('', 'end', iid=str(index), values=self._result_values(row),
                                    tags=(row.get('status', ''),))
        summary = result_summary(result)
        sampling_status = result.get('monte_carlo', {}).get('status')
        if sampling_status == 'required_not_run' and self._can_sample():
            conclusion = '已算工况发现超限。可点击「运行蒙特卡洛」。'
        elif sampling_status == 'skipped_within':
            conclusion = '已覆盖的规格满足。'
        elif sampling_status == 'blocked_incomplete':
            conclusion = '已算工况未确认超限，区间结论待复核。'
        elif sampling_status == 'completed':
            conclusion = '已完成蒙特卡洛。各组失效统计见下方。'
        else:
            conclusion = '已得出复算结果，抽样状态见下方。'
        self.status.set(f'结论 · {conclusion}\n{summary}')
        self.stage_text.set(stage_summary(result))
        theory = theory_summary(result)
        self.theory_text.set(theory)
        if theory:
            self.theory_note.pack(fill='x', before=self.result_frame)
        else:
            self.theory_note.pack_forget()
        if result['rows']:
            self.result_tree.selection_set('0')
            self._selected_result()

    def _selected_result(self, _event=None):
        selected = self.result_tree.selection()
        if not self.result or not selected:
            return
        row = self.result['rows'][int(selected[0])]
        case = row.get('case') or {}
        params = case.get('parameters') or {}
        settings = '、'.join(f"{self.catalog.get(path, {}).get('label', path)} = "
                            f"{_number(value, self.catalog.get(path, {}).get('unit', ''))}"
                            for path, value in params.items())
        lines = [row['name'] + ' · ' + _case_text(case)]
        if case.get('candidate_basis'):
            lines.append('工况选择依据  ' + case['candidate_basis'])
        if row.get('coverage') == 'candidates':
            lines.append('覆盖范围  本轮定向复算的候选工况。')
        if case.get('load_fractions'):
            lines.append('各路负载  ' + ' · '.join(f'OUT{i} {value*100:g}%'
                                                for i, value in enumerate(case['load_fractions'], 1)))
        if settings:
            directions = case.get('deviations') or {}
            if directions:
                touched = {'lower': '下偏', 'upper': '上偏', 'nominal': '标称'}
                summary = ' · '.join(f"{self.catalog.get(path, {}).get('label', path)} {touched.get(side, side)}"
                                      for path, side in directions.items() if side != 'nominal')
                lines.append('偏差组合  ' + (summary or '全标称'))
            lines.append('该工况器件值  ' + settings)
        reason = row.get('reason') or row.get('note')
        if reason:
            lines.append(str(reason))
        stats = row.get('statistics') or {}
        if stats.get('count'):
            lines.append(f"有效 MC 样本 {stats['count']}/{stats.get('attempted', '?')}，均值 {_number(stats.get('mean'))}，"
                         f"标准差 {_number(stats.get('std'))}，预期单尾样本 {_number(stats.get('expected_tail_count'))}。")
            percentiles = [_number(stats.get(key)) for key in ('percentile_05', 'median', 'percentile_95')]
            lines.append('经验分位 P05 / P50 / P95  ' + ' / '.join(percentiles) + ' ' + row.get('unit', ''))
            if stats.get('compared_units'):
                lines.append(f"样本内超限  {stats.get('observed_exceedances', 0)}/{stats['compared_units']}。")
            low, high = stats.get('moment_4sigma_low'), stats.get('moment_4sigma_high')
            if low is not None and high is not None:
                lines.append(f'μ ± 4σ 描述区间  {_number(low)} 至 {_number(high)}。经验分位区间  {self._statistics_text(row)}。')
        failures = self.result.get('failures') or []
        if failures:
            failure = failures[0]
            lines.append('一项失败工况  ' + _case_text(failure) + '  ' + str(failure.get('error') or '求解未完成'))
        self.detail.set('\n'.join(lines))

    @staticmethod
    def _save_json(path, data):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

    def export_result(self, kind):
        try:
            spec = self._get_spec()
        except (TypeError, ValueError, KeyError, tk.TclError):
            spec = None
        result = self.current_result(spec)
        if result is None:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.' + kind,
            filetypes=[('容差评估结果', '*.' + kind)], initialfile=f'{TOLERANCE_TITLE}.{kind}')
        if not path:
            return
        try:
            if kind == 'json':
                self._save_json(path, result)
            else:
                with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    groups = (result.get('monte_carlo') or {}).get('groups') or {}
                    writer.writerow(('指标', '分类', '单位', '阈值', '已算最不利值', '余量', '发生工况',
                                     'MC 超限样本 / 可比', 'MC 4σ 经验分位', '结论', '证据', '器件值（SI）',
                                     '分组失效概率', '分组待判定', '分组观测比例范围', '分组95%区间',
                                     '覆盖范围', '工况选择依据'))
                    for row in result['rows']:
                        group, name, limit, worst, margin, case_text, risk, state = self._result_values(row)
                        case = row.get('case') or {}
                        values = case.get('parameters') or {}
                        probability = groups.get(row.get('group'), {})
                        writer.writerow((name, group, row.get('unit', ''), limit, worst, margin, case_text,
                                         risk, self._statistics_text(row),
                                         state, '设计计算', json.dumps(values, ensure_ascii=False),
                                         probability.get('probability'), probability.get('unknown_units'),
                                         json.dumps(probability['observed_bounds']) if probability.get('observed_bounds') else '',
                                         json.dumps(probability['confidence_interval_95']) if probability.get('confidence_interval_95') else '',
                                         '已算候选工况' if row.get('coverage') == 'candidates' else '',
                                         case.get('candidate_basis', '')))
            self.status.set('容差评估结果已导出。')
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror('导出容差评估结果', str(error), parent=self)

    def current_result(self, spec):
        self.invalidate(spec)
        return self.result
