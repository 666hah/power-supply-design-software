"""Read-only acceptance limits and opt-in evidence editing for two endpoint cases."""
import copy
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

from engineering_acceptance import (CASE_IDS, GROUPS, SOURCES, input_fingerprint, manual_measurement,
                                    normalize, report_snapshot)
from scrollable_results import ScrollableResults

STATUS_LABELS = {'pass': '满足', 'review': '超限', 'undefined': '待补', 'stale': '失效', 'na': '不适用'}
STATUS_COLORS = {'pass': '#167144', 'review': '#b42318', 'undefined': '#966214',
                 'stale': '#b54708', 'na': '#64748b'}
SOURCE_LABELS = dict(zip(SOURCES, ('计算', '仿真', '实测')))
MEASUREMENT_FIELDS = (('value', '实测值'), ('source', '来源 / 仪器'), ('conditions', '测试条件'),
                      ('evidence_ref', '证据文件 / 编号'), ('note', '备注'))
COLUMNS = ('name', 'target', 'Vinmin_values', 'Vinmin_state', 'Vinmax_values', 'Vinmax_state')
VISIBLE_COMPONENT_ROWS = 9


def _fmt(value):
    return '—' if value is None else f'{value:.5g}'


def _limit_text(row):
    if row.get('limits_vary'):
        return '按工况'
    comparison = row['comparison']
    if comparison == 'range':
        if row['lower'] is not None and row['upper'] is not None:
            return f"{_fmt(row['lower'])} … {_fmt(row['upper'])}"
    elif row['limit'] is not None:
        relation = {'<=': '≤', '>=': '≥'}.get(comparison, comparison)
        return f"{relation} {_fmt(row['limit'])}"
    return '—'


def _counts_text(summary):
    counts = summary['counts']
    return ' · '.join(f'{STATUS_LABELS[state]} {counts.get(state, 0)}'
                      for state in ('pass', 'review', 'undefined', 'stale')
                      if state in ('pass', 'review', 'undefined') or counts.get(state, 0))


def _case_status(case):
    return case.get('pending_reason') or STATUS_LABELS[case['status']]


class AcceptancePanel(ttk.Frame):
    def __init__(self, parent, *, get_spec, on_apply, on_refresh=None,
                 get_range_result=None, get_joint_record=None, get_spice_evidence=None,
                 on_import_evidence=None):
        super().__init__(parent)
        self.get_spec, self.on_apply, self.on_refresh = get_spec, on_apply, on_refresh
        self.get_range_result = get_range_result or (lambda: None)
        self.get_joint_record = get_joint_record or (lambda: None)
        self.get_spice_evidence = get_spice_evidence or (lambda: None)
        self.on_import_evidence = on_import_evidence
        self.snapshot, self.selected, self.evidence_window = None, None, None
        self.rows = {}
        self.summary = tk.StringVar(value='待计算 · 请刷新输入端点结果。')
        self.message = tk.StringVar()
        self.notes = tk.StringVar()
        self._matrix_styles = {key: f'Acceptance{id(self)}{key}.Treeview' for key, _ in GROUPS}
        self._last_matrix_layout = None
        self.scroll = ScrollableResults(self)
        self.scroll.pack(fill='both', expand=True)
        host = self.scroll.content

        self.summary_label = ttk.Label(host, textvariable=self.summary, justify='left',
                                       style='ResultConclusion.TLabel', padding=(8, 5))
        self.summary_label.pack(fill='x')
        toolbar = ttk.Frame(host, padding=(8, 4))
        toolbar.pack(fill='x')
        self.refresh_button = ttk.Button(toolbar, text='刷新 Vinmin / Vinmax', command=self.request_refresh)
        self.import_button = ttk.Button(toolbar, text='导入仿真证据…', command=self.import_evidence)
        self.detail_button = ttk.Button(toolbar, text='查看所选证据…', command=self.open_evidence,
                                        state='disabled')
        self.toolbar_buttons = (self.refresh_button, self.import_button, self.detail_button)
        for column, button in enumerate(self.toolbar_buttons):
            button.grid(row=0, column=column, sticky='w', padx=(0, 8), pady=3)
        self.message_label = ttk.Label(host, textvariable=self.message, padding=(8, 3))
        self.notes_label = ttk.Label(host, textvariable=self.notes, style='Muted.TLabel',
                                     justify='left', padding=(8, 3))
        for variable, label in ((self.message, self.message_label), (self.notes, self.notes_label)):
            variable.trace_add('write', lambda *_args, field=variable, widget=label:
                               self._notice_changed(field, widget))

        self.trees, self.group_labels = {}, {}
        for key, title in GROUPS:
            section = ttk.LabelFrame(host, text=title, padding=8)
            section.pack(fill='x', padx=8, pady=(5, 7))
            caption = ttk.Label(section, text='待计算')
            caption.pack(fill='x', pady=(0, 4))
            self.group_labels[key] = caption
            self.trees[key] = self._make_tree(section, self._matrix_styles[key])

        self.bind('<Configure>', self._reflow, add='+')
        for tree in self.trees.values():
            tree.bind('<Configure>', self._reflow, add='+')

    def _notice_changed(self, variable, label):
        if variable.get():
            if label is self.notes_label:
                label.pack(fill='x')
            else:
                label.pack(fill='x', before=self.group_labels[GROUPS[0][0]].master)
        else:
            label.pack_forget()

    def _make_tree(self, parent, style):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=COLUMNS, show='headings', height=1,
                            selectmode='browse', style=style)
        for key, title in zip(COLUMNS, ('验收项 / 单位', '限值', 'Vinmin', '状态', 'Vinmax', '状态')):
            tree.heading(key, text=title)
            tree.column(key, anchor='w', stretch=False)
        sy = ttk.Scrollbar(frame, command=tree.yview)
        sx = ttk.Scrollbar(frame, command=tree.xview, orient='horizontal')
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        tree.pack(fill='x')
        for state, color in STATUS_COLORS.items():
            tree.tag_configure(state, foreground=color)
        tree.bind('<<TreeviewSelect>>', self._select_row)
        tree.bind('<Double-1>', self._open_tree_evidence)
        tree.bind('<Return>', lambda _event: self.open_evidence())
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            tree.bind(sequence, self._scroll_tree)
        return tree

    def _scroll_tree(self, event):
        if event.state & 1:  # Leave Shift + wheel to the table's horizontal scroll.
            return None
        start, end = event.widget.yview()
        if event.num in (4, 5):
            up = event.num == 4
            sequence, options = f'<Button-{event.num}>', {}
        elif event.delta:
            up = event.delta > 0
            sequence, options = '<MouseWheel>', {'delta': event.delta}
        else:
            return None
        if (up and start == 0) or (not up and end == 1):
            self.scroll.canvas.event_generate(sequence, **options)
            return 'break'
        return None

    def _reflow(self, _event=None):
        font = tkfont.nametofont('TkDefaultFont')
        width = max(200, self.winfo_width() - 44)
        tree_widths = tuple(max(1, tree.winfo_width() - 4) for tree in self.trees.values())
        marker = (width, tree_widths, font.actual('size'), font.metrics('linespace'))
        if marker == self._last_matrix_layout:
            return
        self._last_matrix_layout = marker

        available = width
        row, column = 0, 0
        for button in self.toolbar_buttons:
            requested = button.winfo_reqwidth() + 8
            if column and requested > available:
                row, column, available = row + 1, 0, width
            button.grid_configure(row=row, column=column)
            column, available = column + 1, available - requested

        style = ttk.Style(self)
        family, size = font.actual('family'), abs(font.actual('size'))
        for label in (self.summary_label, self.message_label, self.notes_label, *self.group_labels.values()):
            label.configure(wraplength=width)

        proportions = (.29, .10, .18, .125, .18, .125)
        value_sample = '实测 -1.2345e-999'  # Longest form produced by _fmt for a float.
        samples = ('验收项 / 单位', '≥ 0.999', value_sample, '缺限值', value_sample, '缺限值')
        for (group_id, tree), tree_width in zip(self.trees.items(), tree_widths):
            style.configure(self._matrix_styles[group_id] + '.Heading',
                            font=(family, max(10, round(size * .85)), 'bold'))
            table_width = width if tree_width == 1 else tree_width
            for key, fraction, sample in zip(COLUMNS, proportions, samples):
                minimum = font.measure(sample) + 16
                tree.column(key, width=max(minimum, int(table_width * fraction)), minwidth=minimum)
            self._render_values(tree)

    @staticmethod
    def _wrap_cell(tree, text, column):
        font = tkfont.nametofont('TkDefaultFont')
        width = max(30, tree.column(column, 'width') - 12)
        lines, current = [], ''
        for char in text:
            if current and font.measure(current + char) > width:
                lines.append(current)
                current = ''
                if len(lines) == 3:
                    lines[-1] = lines[-1][:-1] + '…'
                    return '\n'.join(lines)
            current += char
        return '\n'.join(lines + [current])

    def _row_values(self, tree, row):
        metric = row['name'] or row['id']
        if row['unit']:
            metric += ' / ' + row['unit']
        values = [self._wrap_cell(tree, metric, 'name'), self._wrap_cell(tree, _limit_text(row), 'target')]
        for case_id in CASE_IDS:
            case = row['cases'][case_id]
            evidence = []
            for source, label in SOURCE_LABELS.items():
                value, state = case[source], case['states'][source]
                if value is None:
                    continue
                display = _fmt(value)
                if state == 'stale' or (state == 'undefined' and source != 'calculation'):
                    display = STATUS_LABELS[state]
                evidence.append(label + ' ' + display)
            values.extend(('\n'.join(evidence) or '—', self._wrap_cell(tree, _case_status(case), case_id + '_state')))
        return values

    def _render_values(self, tree):
        lines = 1
        for key in tree.get_children():
            values = self._row_values(tree, self.rows[key])
            tree.item(key, values=values)
            lines = max(lines, *(text.count('\n') + 1 for text in values))
        font = tkfont.nametofont('TkDefaultFont')
        ttk.Style(self).configure(tree.cget('style'), rowheight=font.metrics('linespace') * lines + 8,
                                  font='TkDefaultFont')

    def request_refresh(self):
        if self.on_refresh is None:
            self.message.set('请先完成双端计算。')
            return
        self.message.set('已请求刷新计算快照。')
        self.on_refresh()

    def import_evidence(self):
        if self.on_import_evidence is None:
            self.message.set('当前项目未接入仿真证据导入。')
            return
        self.on_import_evidence()
        self.refresh()

    def refresh(self):
        previous = self.snapshot
        try:
            self.snapshot = report_snapshot(self.get_spec(), self.get_range_result(), self.get_joint_record(),
                                            self.get_spice_evidence())
        except Exception as exc:
            self.snapshot = None
            self.summary.set('待计算 · 当前验收输入未就绪。\n' + str(exc))
            self.summary_label.configure(foreground=STATUS_COLORS['undefined'])
        self.rows = {row['id']: row for row in self.snapshot['rows']} if self.snapshot else {}
        groups = {group['id']: group['summary'] for group in self.snapshot['groups']} if self.snapshot else {}
        for key, tree in self.trees.items():
            top = tree.yview()[0]
            tree.delete(*tree.get_children())
            for row in self.rows.values():
                if row['group'] == key:
                    states = {case['status'] for case in row['cases'].values()}
                    tag = next(state for state in ('review', 'undefined', 'stale', 'pass', 'na') if state in states)
                    tree.insert('', 'end', iid=row['id'], tags=(tag,))
            count = len(tree.get_children())
            if count:
                tree.configure(height=min(VISIBLE_COMPONENT_ROWS, count) if key == 'components' else count)
                tree.master.pack(fill='x')
                self._render_values(tree)
                tree.yview_moveto(top)
            else:
                tree.master.pack_forget()
            summary = groups.get(key)
            label = self.group_labels[key]
            label.configure(text=f"{summary['label']}   {_counts_text(summary)}" if count else
                            '当前拓扑无适用项' if summary else '等待有效输入',
                            foreground=STATUS_COLORS[summary['state']] if summary else STATUS_COLORS['undefined'])

        if self.snapshot:
            summary = self.snapshot['summary']
            self.summary.set(f"结论 · {summary['label']}\n按输入端点统计  {_counts_text(summary)}")
            self.summary_label.configure(foreground=STATUS_COLORS[summary['state']])
        self.notes.set('\n'.join(self.snapshot['evidence_notes']) if self.snapshot else '')
        same_project = bool(previous and self.snapshot and
                            previous['input_fingerprint'] == self.snapshot['input_fingerprint'] and
                            previous['config'] == self.snapshot['config'])
        selected = self.rows.get(self.selected)
        if selected is None:
            selected = next(iter(self.rows.values()), None)
        if selected:
            self.trees[selected['group']].selection_set(selected['id'])
            self._set_selection(selected, reset=not same_project)
        else:
            self._set_selection(None)
        self._reflow()

    def _select_row(self, event):
        selection = event.widget.selection()
        if selection and selection[0] != self.selected and (row := self.rows.get(selection[0])):
            self._set_selection(row)

    def _set_selection(self, row, *, reset=False):
        current = row['id'] if row else None
        if row:
            for key, tree in self.trees.items():
                if key != row['group']:
                    tree.selection_remove(*tree.selection())
        self.detail_button.configure(state='normal' if row else 'disabled')
        if self.evidence_window is not None:
            if row is None:
                self.close_evidence()
            else:
                self._update_evidence(row, reset=reset or current != self.selected)
        self.selected = current

    def _open_tree_evidence(self, event):
        if event.widget.identify_row(event.y):
            self._select_row(event)
            self.open_evidence()

    def open_evidence(self):
        if not (row := self.rows.get(self.selected)):
            return
        if self.evidence_window is not None:
            self.evidence_window.lift()
            return
        window = self.evidence_window = tk.Toplevel(self)
        window.title('证据详情与实测')
        window.transient(self.winfo_toplevel())
        window.protocol('WM_DELETE_WINDOW', self.close_evidence)
        window.bind('<Escape>', lambda _event: self.close_evidence())
        window.geometry('620x600')
        self.evidence_title = ttk.Label(window, style='ResultConclusion.TLabel',
                                        justify='left', padding=8, wraplength=580)
        self.evidence_title.pack(fill='x')
        tabs = ttk.Notebook(window)
        tabs.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.case_detail, self.measurement, self.confirm_measurement = {}, {}, {}

        for case_id in CASE_IDS:
            scroll = ScrollableResults(tabs)
            tabs.add(scroll, text=case_id)
            panel = scroll.content
            detail = ttk.Label(panel, justify='left', padding=8, wraplength=560)
            detail.pack(fill='x')
            self.case_detail[case_id] = detail
            form = ttk.LabelFrame(panel, text='录入本工况实测', padding=8)
            form.pack(fill='x', padx=8, pady=8)
            fields = {key: tk.StringVar(master=window) for key, _ in MEASUREMENT_FIELDS}
            self.measurement[case_id] = fields
            for index, (key, title) in enumerate(MEASUREMENT_FIELDS):
                ttk.Label(form, text=title).grid(row=index, column=0, sticky='w', pady=2)
                ttk.Entry(form, textvariable=fields[key], width=16).grid(row=index, column=1,
                                                                         sticky='ew', padx=(6, 0), pady=2)
            form.columnconfigure(1, weight=1)
            confirm = self.confirm_measurement[case_id] = tk.BooleanVar(master=window)
            ttk.Checkbutton(form, text='确认对应当前硬件与本工况', variable=confirm).grid(
                row=5, column=0, columnspan=2, sticky='w', pady=4)
            ttk.Button(form, text='应用本工况实测', command=lambda key=case_id: self.apply_measurement(key)).grid(
                row=6, column=0, columnspan=2, sticky='ew', pady=4)
        self.evidence_message = ttk.Label(window, padding=(8, 0, 8, 8), wraplength=580)
        self.evidence_message.pack(fill='x')
        window.bind('<Configure>', self._reflow_evidence, add='+')
        self._update_evidence(row, reset=True)

    def _reflow_evidence(self, event):
        if event.widget is self.evidence_window:
            width = max(160, event.width - 50)
            for label in (self.evidence_title, self.evidence_message, *self.case_detail.values()):
                label.configure(wraplength=width)

    def close_evidence(self):
        if self.evidence_window is not None:
            self.evidence_window.destroy()
            self.evidence_window = None

    def _update_evidence(self, row, *, reset):
        unit = ' / ' + row['unit'] if row['unit'] else ''
        heading = (row['name'] or row['id']) + unit
        if row['note']:
            heading += '\n' + row['note']
        self.evidence_title.configure(text=heading)
        for case_id in CASE_IDS:
            case = row['cases'][case_id]
            lines = [f"结论 · {_case_status(case)}",
                     f"工况 · 输入电压 {_fmt(case['V_in'])} V · 限值 {_limit_text(case)}"]
            for source, label in SOURCE_LABELS.items():
                state = STATUS_LABELS[case['states'][source]]
                value = _fmt(case[source])
                margin = case['margins'][source]
                origin = case['sources'][source]
                result = f'{label} · {value} · {state}'
                if margin is not None:
                    result += f' · 余量 {_fmt(margin)}'
                lines.append(result + (f' · {origin}' if origin else ''))
            for line in (case['reason'], case['calculation_error']):
                if line:
                    lines.append(line)
            self.case_detail[case_id].configure(text='\n'.join(lines))
            if reset:
                record = case.get('measurement_record') or {}
                for key, variable in self.measurement[case_id].items():
                    value = record.get(key)
                    variable.set('' if value is None else str(value))
                self.confirm_measurement[case_id].set(False)
        if reset:
            self.evidence_message.configure(text='')

    def apply_measurement(self, case_id):
        if self.evidence_window is None or not self.selected or not self.snapshot:
            return False
        try:
            p = self.get_spec()
            if input_fingerprint(p) != self.snapshot['input_fingerprint']:
                self.refresh()
                raise ValueError('输入已变化，请按当前硬件与工况重新确认。')
            if not self.confirm_measurement[case_id].get():
                raise ValueError('请确认录入对应当前硬件与本工况。')
            config = normalize(p.get('engineering_acceptance'))
            values = {key: variable.get().strip() for key, variable in self.measurement[case_id].items()}
            if not all(values[key] for key in ('value', 'source', 'conditions')):
                raise ValueError('实测必须填写数值、来源和测试条件。')
            value = float(values.pop('value'))
            record = manual_measurement(p, self.selected, case_id, value, **values)
            config['measurements'] = [m for m in config['measurements'] if
                                      (m['criterion_id'], m['case_id']) != (self.selected, case_id)] + [record]
            if self.on_apply(copy.deepcopy(normalize(config))) is False:
                return False
            self.refresh()
            self.message.set('实测已应用。保存工程后可保留。')
            self.evidence_message.configure(text=self.message.get())
            return True
        except (ValueError, TypeError) as exc:
            messagebox.showerror('请检查实测录入', str(exc), parent=self.evidence_window or self.winfo_toplevel())
            return False
