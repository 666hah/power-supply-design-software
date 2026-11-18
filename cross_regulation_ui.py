"""On-demand display of steady-state regulation at the load corners."""
import queue
import tkinter as tk
from tkinter import ttk


class CrossRegulationUI:
    def _sync_cross_regulation_page(self):
        if not hasattr(self, 'tab_cross'):
            return
        supported = (
            self._inline_multiple_active()
            and self._topo_key() in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
            and self._effective_feedback_mode() == 'SSR'
        )
        try:
            count = self._read_output_count() if supported else 0
        except ValueError:
            count = len(self.output_config)
        state = 'normal' if count >= 2 else 'hidden'
        if self.nb.tab(self.tab_cross, 'state') != state:
            if state == 'hidden' and self.nb.select() == str(self.tab_cross):
                self.nb.select(self.tab_topology)
            self.nb.tab(self.tab_cross, state=state)
            if hasattr(self, '_layout_result_navigation'):
                self._layout_result_navigation()

    def _build_cross_regulation(self, parent):
        self._cross_progress = queue.SimpleQueue()
        self._cross_result = None
        self._cross_progress_token = None
        self._cross_endpoint_data = {}
        self._cross_case_by_id = {}
        self._cross_endpoint_corners = {}
        self._cross_summary_corners = {}
        self.cross_note = tk.StringVar(master=parent, value='准备当前设计后，按需扫描各路轻载与满载组合。')
        self.cross_detail = tk.StringVar(master=parent, value='选中角点可查看电压、负载及求解状态。')
        self._cross_view = ttk.Frame(parent, padding=(12, 8))
        self._cross_view.pack(fill='both', expand=True)
        view = self._cross_view
        title = ttk.Frame(view)
        title.pack(fill='x', pady=(0, 6))
        ttk.Label(title, text='交叉调整率', style='Result.TLabel').pack(side='left')
        self.cross_progressbar = ttk.Progressbar(title, length=132, mode='determinate')
        self.cross_progressbar.pack(side='right', padx=(12, 0), fill='x')

        actions = ttk.Frame(view)
        actions.pack(fill='x', pady=(0, 6))
        self.cross_button = ttk.Button(actions, text='扫描负载角点', style='Accent.TButton',
                                       command=self._start_cross_regulation)
        self.cross_cancel = ttk.Button(actions, text='取消', state='disabled',
                                       command=self._cancel_cross_regulation)
        self.cross_load_button = ttk.Button(actions, text='编辑负载范围', command=self._edit_cross_load_range)
        for i, button in enumerate((self.cross_button, self.cross_cancel, self.cross_load_button)):
            actions.columnconfigure(i, weight=1)
            button.grid(row=0, column=i, sticky='ew', padx=(0, 8 if i < 2 else 0))
        status = ttk.Label(view, textvariable=self.cross_note, style='Guide.TLabel',
                           padding=(8, 4), justify='left', anchor='w')
        status.pack(fill='x', pady=(0, 8))
        status.bind('<Configure>', lambda e: status.configure(wraplength=max(1, e.width - 16)))

        self._cross_summary_book = ttk.Notebook(view)
        summary = ttk.Frame(self._cross_summary_book)
        endpoints = ttk.Frame(self._cross_summary_book)
        self._cross_summary_book.add(summary, text='逐路结论')
        self._cross_summary_book.add(endpoints, text='输入端点对比')
        self.cross_tree = self._cross_table(summary, (
            ('rail', '输出', 104), ('ref', '参考 / V', 90), ('min_w', '轻载 / W', 90),
            ('max_w', '满载 / W', 90), ('range', '电压范围 / V', 135),
            ('deviation', '标称偏差 / %', 130), ('span', '总跨度 / %', 115),
            ('cross', '纯跨调 / %', 115), ('min', '最低角点', 96), ('max', '最高角点', 96),
        ), rows=3)
        self.cross_tree.bind('<ButtonRelease-1>', self._open_summary_corner)
        self.cross_tree.bind('<Return>', self._open_endpoint_for_selection)

        endpoint_actions = ttk.Frame(endpoints, padding=(6, 4))
        endpoint_actions.pack(fill='x')
        ttk.Label(endpoint_actions, text='观察输出').pack(side='left', padx=(0, 6))
        self._cross_rail_picker = ttk.Combobox(endpoint_actions, state='readonly', width=13)
        self._cross_rail_picker.pack(side='left')
        self._cross_rail_picker.bind('<<ComboboxSelected>>', lambda _: self._render_cross_endpoint())
        ttk.Label(endpoint_actions, text='纯跨调固定本路功率和 Vin').pack(side='right')
        self._cross_endpoint_tree = self._cross_table(endpoints, (
            ('metric', '指标', 135), ('vin1', 'Vin', 145), ('vin2', 'Vin max', 145),
        ), rows=5)
        self._cross_endpoint_tree.bind('<ButtonRelease-1>', self._open_endpoint_corner)
        self._cross_endpoint_tree.bind('<Return>', self._open_endpoint_corner)

        corners = ttk.Frame(self._cross_summary_book)
        self._cross_summary_book.add(corners, text='负载角点')
        filters = ttk.Frame(corners, padding=(0, 4))
        filters.pack(fill='x')
        ttk.Label(filters, text='负载角点', style='Result.TLabel').pack(side='left')
        self._cross_filter = ttk.Combobox(filters, values=('全部输入端点',), state='readonly', width=15)
        self._cross_filter.current(0)
        self._cross_filter.pack(side='right')
        self._cross_filter.bind('<<ComboboxSelected>>', lambda _: self._render_cross_cases())
        self._build_cross_detail(corners)
        self.cross_cases = self._cross_table(corners, (
            ('id', '角点', 84), ('vin', 'Vin / V', 92), ('loads', '各路负载 / W', 245),
            ('voltages', '解算电压 / V', 245), ('frequency', '频率 / Hz', 112), ('state', '状态', 132),
        ), rows=5)
        self.cross_cases.bind('<<TreeviewSelect>>', self._select_cross_case)
        self._cross_summary_book.pack(fill='both', expand=True)

    @staticmethod
    def _cross_table(parent, columns, *, rows):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=tuple(key for key, _, _ in columns), show='headings',
                            selectmode='browse', height=rows)
        tree.grid(row=0, column=0, sticky='nsew')
        ybar = ttk.Scrollbar(frame, command=tree.yview)
        ybar.grid(row=0, column=1, sticky='ns')
        xbar = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        xbar.grid(row=1, column=0, sticky='ew')
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        for key, title, width in columns:
            tree.heading(key, text=title, anchor='w' if key == columns[0][0] else 'center')
            tree.column(key, width=width, minwidth=width, anchor='w' if key == columns[0][0] else 'center')
        tree.tag_configure('alternate', background='#f2f6fc')
        tree.tag_configure('review', foreground='#8a4b10')
        return tree

    def _build_cross_detail(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(side='bottom', fill='x', pady=(6, 0))
        self.cross_detail_text = tk.Text(frame, height=2, width=35, wrap='word',
                                        font='TkDefaultFont', relief='flat', padx=6, pady=4)
        self.cross_detail_text.pack(side='left', expand=True, fill='x')
        bar = ttk.Scrollbar(frame, command=self.cross_detail_text.yview)
        bar.pack(side='right', fill='y')
        self.cross_detail_text.configure(yscrollcommand=bar.set)

        def show_detail(*_):
            self.cross_detail_text.configure(state='normal')
            self.cross_detail_text.delete('1.0', 'end')
            self.cross_detail_text.insert('1.0', self.cross_detail.get())
            self.cross_detail_text.configure(state='disabled')

        self.cross_detail.trace_add('write', show_detail)
        show_detail()

    def _edit_cross_load_range(self):
        if hasattr(self, '_set_parameter_pane_visible'):
            self._set_parameter_pane_visible(True)
        self._focus_inline_section('spec')

    def _refresh_cross_inputs(self):
        from isolated_outputs import output_specs

        if self._cross_result and self._cross_result.get('supported'):
            return
        params = self._last.get('calculation_params', self._last['p'])
        rails = output_specs(params)
        self._render_cross_summary(rails, int(params.get('feedback_output', 1)))

    def _mark_cross_regulation_stale(self):
        if not hasattr(self, 'cross_note'):
            return
        self._cross_result = None
        self._cross_progress_token = None
        self._cross_endpoint_data.clear()
        self._cross_case_by_id.clear()
        self._cross_endpoint_corners.clear()
        self._cross_summary_corners.clear()
        self.cross_button.configure(state='normal')
        self.cross_cancel.configure(state='disabled')
        self.cross_progressbar.configure(value=0)
        for tree in (self.cross_tree, self.cross_cases, self._cross_endpoint_tree):
            tree.delete(*tree.get_children())
        self._cross_rail_picker.configure(values=())
        self._cross_rail_picker.set('')
        self._update_cross_endpoint_choices()
        self._rendered_tabs.discard(self.nb.index(self.tab_cross))
        self.cross_note.set('待扫描当前参数。')
        self.cross_detail.set('角点电压为稳态直流平均值。选择角点可查看完整状态。')

    def _start_cross_regulation(self):
        if not self._snapshot_valid or not self._last:
            self.cross_note.set('请等待当前设计计算完成。')
            return
        from cross_regulation import scan_cross_regulation

        self._mark_cross_regulation_stale()
        self._refresh_cross_inputs()
        self.cross_button.configure(state='disabled')
        self.cross_cancel.configure(state='normal')
        token = self._cross_progress_token = object()
        progress = self._cross_progress
        request = dict(p=self._last['p'], calculation_p=self._last.get('calculation_params', self._last['p']))

        def calculate(snapshot, cancelled):
            return scan_cross_regulation(
                snapshot['calculation_p'], cancelled=cancelled,
                progress=lambda done, total, cid: progress.put((token, done, total, cid)),
            )

        self._calculation_worker.submit('cross_regulation', request, calculate, cache=True)
        self.cross_note.set('正在后台计算各输入端点的负载组合。')
        self._ensure_calculation_poll()

    def _cancel_cross_regulation(self):
        if self._cross_progress_token is not None:
            self._calculation_worker.invalidate()
            self._mark_cross_regulation_stale()
            if self._snapshot_valid and self._last:
                self._refresh_cross_inputs()
            self.cross_note.set('扫描已取消。')

    def _drain_cross_progress(self):
        if not hasattr(self, '_cross_progress'):
            return
        last = None
        while not self._cross_progress.empty():
            item = self._cross_progress.get_nowait()
            if item[0] is self._cross_progress_token:
                last = item[1:]
        if last:
            done, total, case = last
            self.cross_progressbar.configure(maximum=total, value=done)
            self.cross_note.set(f'已处理 {done} / {total} 个角点 · {case}')

    def _finish_cross_regulation(self, job):
        if not self._snapshot_valid or not self._last or job.parameters['p'] != self._last['p']:
            return
        self._cross_progress_token = None
        self.cross_button.configure(state='normal')
        self.cross_cancel.configure(state='disabled')
        if job.error is not None:
            self.cross_note.set('扫描失败 · ' + str(job.error))
            return
        data = self._cross_result = job.value
        if not data.get('supported'):
            self.cross_note.set('当前配置未计算 · ' + str(data.get('error')))
            return

        from cross_regulation import for_input

        self._cross_endpoint_data = {vin: for_input(data, vin) for vin in data['voltages']}
        self._cross_case_by_id = {case['id']: case for case in data['cases']}
        self.cross_progressbar.configure(maximum=data['total_cases'], value=data['total_cases'])
        coverage = ' · 部分工况失败，当前仅列出已求解角点范围' if not data['complete'] else ''
        if not data.get('varied_outputs'):
            coverage += ' · 各路轻载功率等于满载功率，未覆盖负载变化'
        self.cross_note.set(f"有效角点 {data['successful_cases']} / {data['total_cases']}" + coverage)
        self._render_cross_summary(data['summary'], data['feedback_output'])
        self._update_cross_endpoint_choices()
        self._render_cross_endpoint()
        self._render_cross_cases()
        self.cross_detail.set(data['note'])

    @staticmethod
    def _cross_result_values(row):
        if row.get('V_min') is None:
            return ('—',) * 6
        return (
            f"{row['V_min']:.5g} ~ {row['V_max']:.5g}",
            f"{row['deviation_min_pct']:+.3g} ~ {row['deviation_max_pct']:+.3g}",
            f"{row['span_pct']:.3g}", f"{row['cross_only_pct']:.3g}",
            row['min_case'], row['max_case'],
        )

    def _render_cross_summary(self, rows, feedback):
        self.cross_tree.delete(*self.cross_tree.get_children())
        self._cross_summary_corners.clear()
        labels = []
        for index, row in enumerate(rows):
            label = f"OUT{row['id']}" + (' ★' if row['id'] == feedback else '')
            labels.append(label)
            ref = row['V_reference'] if 'V_reference' in row else row['V_out']
            light = row['P_min'] if 'P_min' in row else row['P_out_min']
            full = row['P_max'] if 'P_max' in row else row['P_out']
            metrics = self._cross_result_values(row)
            self.cross_tree.insert('', 'end', iid=label, tags=('alternate',) if index % 2 else (),
                                   values=(label, f'{ref:g}', f'{light:g}', f'{full:g}', *metrics))
            if row.get('min_case'):
                self._cross_summary_corners[label] = (row['min_case'], row['max_case'])
        previous = self._cross_rail_picker.get()
        self._cross_rail_picker.configure(values=labels)
        if labels:
            self._cross_rail_picker.current(labels.index(previous) if previous in labels else 0)

    def _update_cross_endpoint_choices(self):
        labels = ['全部输入端点']
        labels.extend(f'{vin:g} V' for vin in self._cross_endpoint_data)
        self._cross_filter.configure(values=labels)
        self._cross_filter.current(0)
        tree = self._cross_endpoint_tree
        tree.configure(displaycolumns=('metric', 'vin1', 'vin2') if len(labels) > 2 else ('metric', 'vin1'))
        if len(labels) == 2:
            tree.heading('vin1', text=f'Vin · {labels[1]}')
        elif len(labels) > 2:
            tree.heading('vin1', text=f'Vin min · {labels[1]}')
            tree.heading('vin2', text=f'Vin max · {labels[-1]}')
        else:
            tree.heading('vin1', text='Vin')

    def _render_cross_endpoint(self):
        tree = self._cross_endpoint_tree
        tree.delete(*tree.get_children())
        self._cross_endpoint_corners.clear()
        i = self._cross_rail_picker.current()
        if i < 0 or not self._cross_endpoint_data:
            return
        comparisons = tuple(self._cross_endpoint_data.values())
        values = [self._cross_result_values(data['summary'][i]) for data in comparisons]
        for row, title in enumerate(('电压范围 / V', '标称偏差 / %', '总跨度 / %', '纯跨调 / %', '最低角点', '最高角点')):
            cells = tuple(column[row] for column in values)
            tree.insert('', 'end', iid=str(row), tags=('alternate',) if row % 2 else (), values=(title, *cells))
            if row in (4, 5):
                for column, cell in enumerate(cells, start=2):
                    if cell in self._cross_case_by_id:
                        self._cross_endpoint_corners[(str(row), f'#{column}')] = cell
        tree.insert('', 'end', values=('有效角点', *(f"{d['successful_cases']} / {d['total_cases']}" for d in comparisons)))

    def _render_cross_cases(self):
        from cross_regulation import load_label

        self.cross_cases.delete(*self.cross_cases.get_children())
        selected = self._cross_filter.current()
        cases = self._cross_case_by_id.values()
        if selected > 0:
            cases = tuple(self._cross_endpoint_data.values())[selected - 1]['cases']
        for index, case in enumerate(cases):
            state = {'ok': '已求解', 'unavailable': '未计算', 'failed': '求解失败'}[case['status']]
            if (case.get('qr_timing') or {}).get('design_frequency_limit_exceeded'):
                state = '频率超限'
            tags = []
            if index % 2:
                tags.append('alternate')
            if state != '已求解':
                tags.append('review')
            self.cross_cases.insert('', 'end', iid=case['id'], tags=tags, values=(
                case['id'], f"{case['V_in']:g}", load_label(case),
                '；'.join(f'OUT{i+1}={v:.5g}' for i, v in enumerate(case['voltages'])) if case['voltages'] else '—',
                f"{case['f_sw']:.5g}" if case.get('f_sw') else '—', state,
            ))

    def _open_summary_corner(self, event):
        row = self.cross_tree.identify_row(event.y)
        column = self.cross_tree.identify_column(event.x)
        corners = self._cross_summary_corners.get(row)
        if corners and column in ('#9', '#10'):
            self._show_cross_corner(corners[0 if column == '#9' else 1])

    def _open_endpoint_for_selection(self, _event):
        selection = self.cross_tree.selection()
        if selection:
            self._cross_rail_picker.set(selection[0])
            self._render_cross_endpoint()
            self._cross_summary_book.select(1)

    def _open_endpoint_corner(self, event):
        tree = self._cross_endpoint_tree
        if event.type == tk.EventType.KeyPress:
            row, column = tree.focus(), '#2'
        else:
            row, column = tree.identify_row(event.y), tree.identify_column(event.x)
        self._show_cross_corner(self._cross_endpoint_corners.get((row, column)))

    def _show_cross_corner(self, case_id):
        if not case_id:
            return
        if not self.cross_cases.exists(case_id):
            self._cross_filter.current(0)
            self._render_cross_cases()
        self.cross_cases.selection_set(case_id)
        self.cross_cases.focus(case_id)
        self._cross_summary_book.select(2)
        self.cross_cases.see(case_id)
        self._select_cross_case()

    def _select_cross_case(self, _event=None):
        selected = self.cross_cases.selection()
        if not selected:
            return
        case = self._cross_case_by_id.get(selected[0])
        if case is None:
            return

        from cross_regulation import load_label
        lines = [f'{case["id"]} · Vin {case["V_in"]:g} V · ' + load_label(case)]
        if case['error']:
            lines.append(case['error'])
        else:
            if case.get('actual_powers'):
                lines.append('端口电压与实际功率 · ' + '，'.join(
                    f'OUT{i} {voltage:.5g} V / {power:.5g} W'
                    for i, (voltage, power) in enumerate(zip(case['voltages'], case['actual_powers']), start=1)
                ))
            lines.append(f'周期电流和电荷平衡归一化残差 {case["residual"]:.3g}。')
        model = case.get('qr_timing')
        if model:
            timing = model.get('timing_policy', '矩阵退磁与离散谷底时序')
            if case.get('f_sw'):
                timing += f' · 实际频率 {case["f_sw"]:.6g} Hz'
            if model.get('design_frequency_limit_exceeded'):
                timing += f' · 超过设计上限 {model["design_frequency_limit_hz"]:g} Hz'
            lines.append(timing)
            rcd = model.get('rcd_hardware')
            if rcd:
                lines.append(f'固定 RCD 平均钳位 {model["clamp_voltage"]:.5g} V，'
                             f'R={rcd["R_ohm"]:.5g} Ω，C={rcd["C_F"]:.5g} F。'
                             f'Q/C 相对纹波上界约 {model["rcd_ripple_upper_relative"]*100:.3g}%。')
        self.cross_detail.set('\n'.join(lines))
