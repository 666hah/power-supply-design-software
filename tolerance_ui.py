"""Desktop editor and result projection for fixed-hardware tolerance analysis."""

import csv
from copy import deepcopy
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from engineering_acceptance import input_fingerprint
from scrollable_results import ScrollableResults


DISTRIBUTIONS = {
    'bounds': '只使用上下限', 'uniform': '均匀分布',
    'triangular': '三角分布', 'normal': '截断正态分布',
}
STATES = {'review': '超限', 'incomplete': '覆盖未完成',
          'within': '已算工况内满足', 'unbounded': '待补阈值'}
PROFILE_SCHEMA = 'powerdesign-tolerance-profile-1'


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
        self.result = None
        self.fingerprint = None
        self.acceptance = None
        self.running = False
        self.stale = False
        self.status = tk.StringVar(value='添加有来源的器件容差，再运行校核。')
        self.detail = tk.StringVar(value='选中结果行可查看最坏工况及统计覆盖。')
        self.samples = tk.StringVar(value='0')
        self.seed = tk.StringVar(value='1')
        self.load_percents = tk.StringVar(value='10, 50, 100')
        self.mixed_loads = tk.StringVar()
        self.max_evaluations = tk.StringVar(value='2000')

        scroll = ScrollableResults(self)
        scroll.pack(fill='both', expand=True)
        host = scroll.content
        self._wrap = []
        self._groups = []
        ttk.Label(host, text='固定硬件容差校核', style='Margin.TLabel', padding=(8, 6)).pack(fill='x')
        self._note(host, '在当前输入范围和所选负载下扫描器件上下限。可选蒙特卡洛，按提供的分布计算同一套硬件的统计结果。')
        variables = ttk.LabelFrame(host, text='器件容差 · 绝对值（SI）', padding=(2, 4))
        variables.pack(fill='x', padx=8, pady=4)
        self.param_tree = make_tree(variables, ('name', 'nominal', 'low', 'high', 'dist', 'group', 'source'),
            ('参数', '当前标称值', '下限', '上限', '分布', '相关组', '依据'),
            (200, 115, 105, 105, 130, 100, 180), height=4)
        self.param_tree.bind('<Double-1>', lambda _event: self.edit_variable(), add='+')
        controls = ttk.Frame(variables)
        controls.pack(fill='x', padx=4, pady=(2, 4))
        self.edit_buttons = self._buttons(controls, (
            ('添加参数…', lambda: self.edit_variable(new=True)), ('编辑选中…', self.edit_variable),
            ('删除选中', self.remove_variable), ('保存容差配置…', self.save_profile), ('导入容差配置…', self.import_profile),
        ))

        options = ttk.LabelFrame(host, text='计算设置', padding=6)
        options.pack(fill='x', padx=8, pady=4)
        entries = ttk.Frame(options)
        entries.pack(fill='x')
        settings = [(self.load_percents, '负载 / %', 15), (self.samples, 'MC 样本数', 10),
                    (self.seed, '随机种子', 8), (self.max_evaluations, '总计算次数上限', 10)]
        self.option_inputs = []
        pairs = []
        for var, title, width in settings:
            pair = ttk.Frame(entries, padding=(2, 2))
            ttk.Label(pair, text=title).pack(anchor='w')
            field = ttk.Entry(pair, textvariable=var, width=width)
            field.pack(fill='x')
            self.option_inputs.append(field)
            pairs.append(pair)
            var.trace_add('write', self._settings_changed)
        self._groups.append((entries, pairs))
        ttk.Label(options, text='各路负载组合 / %（可空）').pack(anchor='w', padx=4)
        mixed = ttk.Entry(options, textvariable=self.mixed_loads)
        mixed.pack(fill='x', padx=4, pady=(0, 3))
        self.option_inputs.append(mixed)
        self.mixed_loads.trace_add('write', self._settings_changed)
        self._note(options, '三路示例填写「主路轻载=10/100/100」。多组用分号分隔，各值按 OUT1、OUT2… 顺序。')
        self._note(options, 'MC 样本数为 0 时只扫描规格上下限。正态分布的 σ 需按厂家资料或批量数据填写，软件不从公差反推。')
        actions = ttk.Frame(options)
        actions.pack(fill='x')
        self.run_button, self.cancel_button, self.csv_button, self.json_button = self._buttons(actions, (
            ('开始校核', self.run), ('取消任务', self._cancel),
            ('导出 CSV…', lambda: self.export_result('csv')), ('导出详细 JSON…', lambda: self.export_result('json')),
        ))
        self.progress_bar = ttk.Progressbar(options, maximum=1)
        self.progress_bar.pack(fill='x', padx=4, pady=(4, 1))
        self._note(host, variable=self.status)

        result = ttk.LabelFrame(host, text='最坏工况表 · 设计计算', padding=(2, 4))
        result.pack(fill='x', padx=8, pady=4)
        self.result_tree = make_tree(result,
            ('name', 'limit', 'worst', 'margin', 'case', 'moment', 'coverage', 'state'),
            ('指标', '阈值', '上下限扫描最坏值', '余量', '发现工况', 'MC μ±4σ', 'MC 4σ 经验分位', '扫描结论'),
            (190, 105, 145, 90, 195, 155, 150, 125), height=8)
        self.result_tree.bind('<<TreeviewSelect>>', self._selected_result, add='+')
        self._note(result, variable=self.detail)
        for tree in (self.param_tree, self.result_tree):
            for column in tree['columns']:
                tree.column(column, stretch=False)
        self.result_tree.tag_configure('incomplete', foreground='#a83232')
        self.result_tree.tag_configure('within', foreground='#197442')
        self.result_tree.tag_configure('unbounded', foreground='#64748b')
        self.bind('<Configure>', self._reflow, add='+')
        self.bind('<Map>', self._on_map, add='+')
        self._update_buttons()

    def _note(self, parent, text='', variable=None):
        label = ttk.Label(parent, text=text, textvariable=variable, wraplength=780,
                          justify='left', padding=(6, 3))
        label.pack(fill='x')
        self._wrap.append(label)

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
        self.catalog = {row['path']: row for row in available_variables(self._get_spec())}
        self._render_variables()

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

    def _settings(self):
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
        try:
            samples, seed, capacity = (int(var.get()) for var in
                                       (self.samples, self.seed, self.max_evaluations))
        except ValueError:
            raise ValueError('样本数、随机种子和总计算次数上限需要填写整数。') from None
        if samples < 0 or not 0 <= seed < 2**32 or capacity <= 0:
            raise ValueError('样本数不得为负，随机种子需在 0–4294967295 内，计算上限须大于 0。')
        return dict(samples=samples, seed=seed, load_fracs=tuple(numeric), load_profiles=profiles,
                    max_evaluations=capacity)

    def _settings_changed(self, *_args):
        if self.result is not None:
            self._clear_result('容差配置已变化，请重新运行。')

    def invalidate(self, spec):
        if self.fingerprint is None:
            return
        try:
            unchanged = (spec is not None and input_fingerprint(spec) == self.fingerprint
                         and (spec.get('engineering_acceptance') or {}) == self.acceptance)
        except (ValueError, TypeError, KeyError):
            unchanged = False
        if not unchanged and not self.stale:
            self.stale = True
            if self.running:
                self._cancel()
            self._clear_result('当前设计参数已变化，请重新运行。')

    def _clear_result(self, status):
        self.result = None
        self.status.set(status)
        self.detail.set('选中结果行可查看最坏工况及统计覆盖。')
        self.result_tree.delete(*self.result_tree.get_children())
        self._update_buttons()

    def _update_buttons(self):
        for widget in (*self.edit_buttons, *self.option_inputs, self.run_button):
            widget.state(('disabled',) if self.running else ('!disabled',))
        self.cancel_button.state(('!disabled',) if self.running and not self.stale else ('disabled',))
        for widget in (self.csv_button, self.json_button):
            widget.state(('!disabled',) if self.result is not None else ('disabled',))

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
                  for key in ('low', 'high', 'sigma', 'source', 'group')}
        dist = tk.StringVar(master=dialog, value=DISTRIBUTIONS[saved.get('distribution', 'bounds')])
        selected = tk.StringVar(master=dialog, value=next((name for name, path in choices.items() if path == previous), next(iter(choices))))
        nominal = tk.StringVar(master=dialog)
        ttk.Label(dialog, text='器件参数').grid(row=0, column=0, sticky='w', padx=10, pady=5)
        ttk.Combobox(dialog, textvariable=selected, values=tuple(choices), state='readonly', width=45).grid(
            row=0, column=1, columnspan=2, sticky='ew', padx=10, pady=5)
        ttk.Label(dialog, textvariable=nominal).grid(row=1, column=0, columnspan=3, sticky='w', padx=10, pady=4)
        entries = {}
        for index, (key, title) in enumerate((('low', '容差下限'), ('high', '容差上限'), ('sigma', '正态分布 σ'),
                     ('source', '依据／来源'), ('group', '相关组（可空）')), 2):
            ttk.Label(dialog, text=title).grid(row=index, column=0, sticky='w', padx=10, pady=4)
            entries[key] = ttk.Entry(dialog, textvariable=fields[key])
            entries[key].grid(row=index, column=1, columnspan=1 if key == 'sigma' else 2,
                              sticky='ew', padx=10, pady=4)
        ttk.Label(dialog, text='分布').grid(row=7, column=0, sticky='w', padx=10, pady=4)
        ttk.Combobox(dialog, textvariable=dist, values=tuple(DISTRIBUTIONS.values()), state='readonly').grid(
            row=7, column=1, columnspan=2, sticky='ew', padx=10, pady=4)
        ttk.Label(dialog, text='同名相关组共用抽样分位。三角分布以标称值为众数。按 4σ 换算是用户假设，建议在来源栏记录依据。',
                  wraplength=510).grid(row=8, column=0, columnspan=3, sticky='w', padx=10, pady=6)

        def sigma_from_bounds():
            try:
                low = _numeric(fields['low'].get(), '容差下限')
                high = _numeric(fields['high'].get(), '容差上限')
                center = self.catalog[choices[selected.get()]]['nominal']
                if low >= high or not math.isclose(center-low, high-center, rel_tol=1e-7):
                    raise ValueError('按 4σ 换算需要上下限关于标称值对称。')
            except ValueError as error:
                messagebox.showerror('换算 σ', str(error), parent=dialog)
                return
            fields['sigma'].set(f'{(high-low)/8:.12g}')

        sigma_button = ttk.Button(dialog, text='按 ±4σ 换算', command=sigma_from_bounds)
        sigma_button.grid(row=4, column=2, sticky='e', padx=(0, 10), pady=4)

        def refresh(*_):
            item = self.catalog[choices[selected.get()]]
            unit = item.get('unit') or ''
            nominal.set('标称值 ' + _number(item['nominal'], unit) + f'，上下限和 σ 按 {unit or "无量纲"} 输入。')
            state = ('!disabled',) if dist.get() == DISTRIBUTIONS['normal'] else ('disabled',)
            entries['sigma'].state(state)
            sigma_button.state(state)

        def apply():
            path = choices[selected.get()]
            distribution = next(key for key, label in DISTRIBUTIONS.items() if label == dist.get())
            try:
                row = _profile_variable(dict(path=path, distribution=distribution,
                                             **{key: var.get() for key, var in fields.items()}))
                if not row['low'] <= self.catalog[path]['nominal'] <= row['high']:
                    raise ValueError('标称值须在容差上下限内。')
            except (KeyError, ValueError) as error:
                messagebox.showerror('器件容差', str(error), parent=dialog)
                return
            if previous is not None and path != previous:
                del self.variables[previous]
            self.variables[path] = row
            self._render_variables()
            self.param_tree.selection_set(path)
            self._clear_result('容差配置已更新。可运行校核或保存配置。')
            dialog.destroy()

        selected.trace_add('write', refresh)
        dist.trace_add('write', refresh)
        refresh()
        actions = ttk.Frame(dialog)
        actions.grid(row=9, column=0, columnspan=3, sticky='e', padx=10, pady=10)
        ttk.Button(actions, text='取消', command=dialog.destroy).pack(side='left', padx=4)
        ttk.Button(actions, text='应用', command=apply).pack(side='left', padx=4)
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.grab_set()

    def remove_variable(self):
        for path in self.param_tree.selection():
            self.variables.pop(path, None)
        self._render_variables()
        self._clear_result('容差配置已更新。')

    def save_profile(self):
        try:
            profile = dict(schema=PROFILE_SCHEMA, variables=list(self.variables.values()), **self._settings())
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
            rows = profile.get('variables', [])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError('容差参数列表格式无效。')
            variables = {row['path']: row for row in map(_profile_variable, rows)}
            if len(variables) != len(rows):
                raise ValueError('配置中有重复的容差参数。')
            options = (profile.get('samples', 0), profile.get('seed', 1), profile.get('max_evaluations', 2000))
            loads = profile.get('load_fracs', [.1, .5, 1.])
            mixed = profile.get('load_profiles', {})
            if (any(type(value) is not int for value in options) or options[0] < 0 or not 0 <= options[1] < 2**32 or options[2] <= 0
                    or not isinstance(loads, list) or any(type(x) not in (int, float) or not 0 < x <= 1 for x in loads)
                    or len(set(loads)) != len(loads)):
                raise ValueError('样本、种子、计算次数上限或负载范围无效。')
            if (not isinstance(mixed, dict) or any(not name.strip() or any(c in name for c in '=;；')
                    or not isinstance(values, list) or not values
                    or any(type(x) not in (int, float) or not 0 < x <= 1 for x in values)
                    for name, values in mixed.items()) or not (loads or mixed)):
                raise ValueError('各路负载组合格式无效。')
            self._refresh_catalog()
        except (KeyError, OSError, TypeError, ValueError, tk.TclError) as error:
            messagebox.showerror('导入容差配置', str(error), parent=self)
            return
        self.variables = variables
        self.load_percents.set(', '.join(f'{value*100:g}' for value in loads))
        self.mixed_loads.set('; '.join(name+'='+'/'.join(f'{value*100:g}' for value in values)
                                     for name, values in mixed.items()))
        for var, value in zip((self.samples, self.seed, self.max_evaluations), options):
            var.set(str(value))
        self._render_variables()
        self._clear_result('容差配置已导入。请核对当前标称值并运行。')

    def run(self):
        try:
            if not self.variables:
                raise ValueError('请至少添加一项器件容差。')
            settings = self._settings()
            self._refresh_catalog()
            variables = [dict(row) for row in self.variables.values()]
            for row in variables:
                item = self.catalog.get(row['path'])
                if not item:
                    raise ValueError(f"{row['path']} 不适用于当前设计。")
                if not row['low'] <= item['nominal'] <= row['high']:
                    raise ValueError(f"{item['label']} 的当前标称值不在所填容差范围内。")
                if settings['samples'] and row['distribution'] == 'bounds':
                    raise ValueError(f"{item['label']} 尚未指定蒙特卡洛分布。")
            spec = self._get_spec()
            output_count = len(spec.get('outputs') or [spec])
            for name, values in settings['load_profiles'].items():
                if len(values) != output_count:
                    raise ValueError(f'{name} 应为当前设计的 {output_count} 路输出各填写一个比例。')
            self._start(spec, variables, settings)
        except (KeyError, TypeError, ValueError, tk.TclError) as error:
            messagebox.showerror('最坏工况校核', str(error), parent=self)

    def started(self, spec):
        self.fingerprint = input_fingerprint(spec)
        self.acceptance = deepcopy(spec.get('engineering_acceptance') or {})
        self.stale = False
        self.running = True
        self.progress_bar.configure(value=0, maximum=1)
        self._clear_result('正在准备固定硬件及器件容差工况…')

    def progress(self, done, total, label):
        if not self.stale:
            self.progress_bar.configure(maximum=max(1, total), value=done)
            self.status.set(f'正在计算 {label} · {done}/{total}')

    def finished(self, *, result=None, error=None, cancelled=False):
        self.running = False
        if self.stale:
            self._clear_result('当前设计参数已变化，请重新运行。')
        elif cancelled:
            self._clear_result('任务已取消。')
        elif error is not None:
            self._clear_result(error)
            messagebox.showerror('最坏工况校核', error, parent=self)
        else:
            self._show_result(result)
        self._update_buttons()

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
        low, high = (stats.get('moment_4sigma_low'), stats.get('moment_4sigma_high'))
        moments = '—' if low is None or high is None else f'{_number(low)} 至 {_number(high, unit)}'
        return (row['name'], f'{relation} {_number(limit, unit)}'.strip() if limit is not None else '—',
                _number(row.get('worst'), unit), _number(row.get('margin'), unit), _case_text(case),
                moments, self._statistics_text(row), STATES.get(row.get('status'), '待复核'))

    def _show_result(self, result):
        self.result = result
        for index, row in enumerate(result['rows']):
            self.result_tree.insert('', 'end', iid=str(index), values=self._result_values(row),
                                    tags=(row.get('status', ''),))
        self.status.set(f"已完成 {result.get('evaluations', 0)} 次计算，设定 {result.get('samples', 0)} 个 MC 样本。"
                        f"失败 {result.get('failure_count', 0)} 次。上下限最坏值适用于本次已扫描工况。")
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
        if case.get('load_fractions'):
            lines.append('各路负载  ' + ' · '.join(f'OUT{i} {value*100:g}%'
                                                for i, value in enumerate(case['load_fractions'], 1)))
        if settings:
            lines.append('最坏工况参数  ' + settings)
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
            filetypes=[('最坏工况结果', '*.' + kind)], initialfile='最坏工况与容差.' + kind)
        if not path:
            return
        try:
            if kind == 'json':
                self._save_json(path, result)
            else:
                with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(('指标', '单位', '阈值', '上下限扫描最坏值', '余量', '发现工况',
                                     'MC μ±4σ', 'MC 4σ 经验分位', '结论', '证据', '器件值（SI）'))
                    for row in result['rows']:
                        name, limit, worst, margin, case, moment, coverage, state = self._result_values(row)
                        values = (row.get('case') or {}).get('parameters') or {}
                        writer.writerow((name, row.get('unit', ''), limit, worst, margin, case, moment, coverage,
                                         state, '设计计算', json.dumps(values, ensure_ascii=False)))
            self.status.set('最坏工况结果已导出。')
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror('导出最坏工况结果', str(error), parent=self)

    def current_result(self, spec):
        self.invalidate(spec)
        return self.result
