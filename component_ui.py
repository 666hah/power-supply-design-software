"""One desktop editor for all active designators, identity and ratings."""
import copy
import math
import tkinter as tk
from tkinter import font, ttk, messagebox

from component_management import (normalize_management, evaluate_components, CAP_TYPES,
                                  RATINGS_BY_KIND, RATING_FIELDS, RULES, SOURCE_NOTE, TEXT_FIELDS,
                                  rating_text, check_text)

class ComponentManager(ttk.Frame):
    def __init__(self, parent, context, changed, *, on_select=None, on_view_topology=None, viewport=None):
        super().__init__(parent, padding=8)
        self.context, self.changed = context, changed
        self.on_select = on_select
        self.config_data = normalize_management()
        self.current = None
        self.loading = False
        self._stale = False
        self._selection_cleared = False
        self.draft = {}
        self.pack(fill='both', expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        table_size = min(17, max(13, abs(font.nametofont('TkDefaultFont', root=self).cget('size'))))
        style = ttk.Style(self)
        style.configure('BOM.Treeview', font=('Microsoft YaHei UI', -table_size), rowheight=table_size + 12)
        style.configure('BOM.Treeview.Heading', font=('Microsoft YaHei UI', -table_size, 'bold'))
        self.summary = tk.StringVar(value='待计算 · 应力和降额结果将在计算完成后显示。')
        summary_label = ttk.Label(self, textvariable=self.summary, wraplength=1080, justify='left',
                                  style='ResultConclusion.TLabel')
        summary_label.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        scope = ttk.Frame(self)
        scope.grid(row=1, column=0, sticky='ew', pady=(0, 5))
        scope_note = ttk.Label(scope, text='本表按当前输入电压和负载初筛。', style='Muted.TLabel', justify='left')
        scope_note.pack(side='left', fill='x', expand=True)
        policy = ttk.Button(scope, text='设置降额规则…', command=self.edit_policy)
        policy.pack(side='right', padx=(8, 0))
        box = ttk.Frame(self); box.grid(row=2, column=0, sticky='nsew')
        box.columnconfigure(0, weight=1); box.rowconfigure(0, weight=1)
        cols = ('ref', 'role', 'manufacturer', 'model', 'package', 'rating', 'status')
        self.tree = ttk.Treeview(box, columns=cols, show='headings', height=15, selectmode='browse', style='BOM.Treeview')
        for key,label,width in zip(cols, ('位号','器件与输出','制造商','型号','封装','额定值','初筛状态'), (90,220,130,160,120,250,145)):
            self.tree.heading(key, text=label); self.tree.column(key, width=width, minwidth=75, stretch=True)
        self.tree.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(box, command=self.tree.yview); sy.grid(row=0,column=1,sticky='ns')
        sx = ttk.Scrollbar(box, orient='horizontal', command=self.tree.xview); sx.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.tag_configure('review', foreground='#b3261e')
        self.tree.tag_configure('undefined', foreground='#996100')
        self.tree.tag_configure('stale', foreground='#64748b')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        detail = self._form = ttk.LabelFrame(self, text='所选器件资料', padding=7)
        detail.grid(row=3, column=0, sticky='ew', pady=6)
        for c in (1,3,5): detail.columnconfigure(c, weight=1)
        labels = [('manufacturer','制造商'),('model','型号'),('package','封装'),
                  ('voltage_V','耐压 / V'),('current_rms_A','允许 RMS / A'),
                  ('current_avg_A','允许正向平均 / A'),('current_peak_A','允许重复峰值 / A'),
                  ('ripple_A','纹波能力 / A RMS'),('power_W','额定功耗 / W'),
                  ('capacitor_type','电容类型'),
                  ('conditions','额定条件 / 来源'),('note','备注')]
        self.editors = {}
        self._form_pairs = {}
        self.voltage_caption = tk.StringVar(value='耐压 / V')
        self.cap_type = tk.StringVar(value=CAP_TYPES['unknown'])
        for key,label in labels:
            caption = ttk.Label(detail, text=label, textvariable=self.voltage_caption if key=='voltage_V' else '')
            if key == 'capacitor_type':
                editor = self.cap_select = ttk.Combobox(detail, textvariable=self.cap_type,
                                                       values=list(CAP_TYPES.values()), state='readonly', width=19)
            else:
                self.draft[key] = tk.StringVar()
                editor = self.editors[key] = ttk.Entry(detail, textvariable=self.draft[key], width=18)
            self._form_pairs[key] = (caption, editor)
        self.selected_label = tk.StringVar(value='先在上表选择器件')
        self._form_footer=ttk.Frame(detail)
        ttk.Label(self._form_footer, textvariable=self.selected_label).pack(side='left',fill='x',expand=True)
        self._apply_button = ttk.Button(self._form_footer, text='应用当前器件', command=self.apply_item)
        self._apply_button.pack(side='right')
        self._view_button = None
        if on_view_topology is not None:
            self._view_button = ttk.Button(self._form_footer, text='在拓扑中查看',
                                           command=lambda: on_view_topology(self.current))
            self._view_button.pack(side='right', padx=(0, 6))
        self._form_columns=0
        def reflow(event):
            columns=3 if event.width>=850 else 2 if event.width>=530 else 1
            if columns != self._form_columns:
                self._form_columns = columns
                self._layout_form()
        detail.bind('<Configure>',reflow)
        text_host=ttk.Frame(self);text_host.grid(row=4,column=0,sticky='ew')
        self.detail = tk.Text(text_host, height=6, wrap='word', font=('Microsoft YaHei',10), relief='flat')
        self.detail.pack(side='left',fill='both',expand=True)
        sy=ttk.Scrollbar(text_host,command=self.detail.yview);sy.pack(side='right',fill='y')
        self.detail.configure(yscrollcommand=sy.set)
        footnote = ttk.Label(self, text='额定值按单颗填写，未知时留空。更换型号后请核对电气参数和曲线。',
                             style='Muted.TLabel', wraplength=1080)
        footnote.grid(row=5,column=0,sticky='ew',pady=4)
        def wrap(event):
            width=max(250,event.width-20)
            summary_label.configure(wraplength=width)
            scope_note.configure(wraplength=max(80, width - policy.winfo_reqwidth() - 8))
            footnote.configure(wraplength=width)
        self.bind('<Configure>',wrap)
        self.rows = {}
        self.loaded_item = None
        self._clear_editor()
        if viewport is not None:
            def resize_list(height):
                if height > 1:
                    # Keep most of the first screen for the list. The outer
                    # scroll view keeps all fields below the list reachable.
                    rows = max(10, min(24, (int(height * .65) - 24) // (table_size + 12)))
                    if int(self.tree.cget('height')) != rows:
                        self.tree.configure(height=rows)

            resize_id = viewport.bind('<Configure>', lambda event: resize_list(event.height), add='+')
            resize_list(viewport.winfo_height())

            def release_resize(event):
                if event.widget is self and viewport.winfo_exists():
                    viewport.unbind('<Configure>', resize_id)

            self.bind('<Destroy>', release_resize, add='+')

    def _layout_form(self):
        columns = self._form_columns or 3
        kind = self.rows.get(self.current, {}).get('kind')
        fields = set(TEXT_FIELDS).union(RATINGS_BY_KIND.get(kind, ()))
        if kind == 'capacitor':
            fields.add('capacitor_type')
        for col in range(6):
            self._form.columnconfigure(col, weight=int(col < columns * 2 and col % 2))
        index = 0
        for key, (label, editor) in self._form_pairs.items():
            if key in fields:
                row, col = divmod(index, columns)
                label.grid(row=row, column=2*col, sticky='w', padx=(0, 5), pady=3)
                editor.grid(row=row, column=2*col+1, sticky='ew', padx=(0, 12), pady=3)
                index += 1
            else:
                label.grid_remove()
                editor.grid_remove()
        self._form_footer.grid(row=math.ceil(index/columns), column=0, columnspan=columns*2, sticky='ew', pady=4)

    def refresh(self, preserve=False):
        p, res = self.context()
        candidate = normalize_management(p.get('component_management'))
        preserve = bool(self.current and (preserve or candidate == self.config_data and self._has_draft()))
        data = evaluate_components(p, res)
        previous_rows = self.rows
        status_changed = self._stale
        self._stale = False
        self.config_data = candidate
        self.rows = {r['ref']:r for r in data['rows']}
        old_order = self.tree.get_children()
        order_changed = old_order != tuple(self.rows)
        removed = [ref for ref in old_order if ref not in self.rows]
        if removed:
            self.tree.delete(*removed)
        for index, (ref, row) in enumerate(self.rows.items()):
            item = previous_rows.get(ref)
            if item == row and not status_changed and not order_changed:
                continue
            values = (ref, row['role'], row.get('manufacturer') or '待填', row.get('model') or '待填',
                      row.get('package') or '待填', rating_text(row), row['status'])
            if item is None:
                self.tree.insert('', index, iid=ref, values=values, tags=(row['state'],))
            else:
                if order_changed and self.tree.index(ref) != index:
                    self.tree.move(ref, '', index)
                if status_changed or item != row:
                    self.tree.item(ref, values=values, tags=(row['state'],))
        counts = data['counts']
        self.summary.set(f"结论 · 超限 {counts['review']} 项 · 待补或待复核 {counts['undefined']} 项  "
                         f"（{data['zone']} 区，共 {len(data['rows'])} 个器件与参考项）")
        if self.current in self.rows:
            self._sync_selection()
            if status_changed or previous_rows.get(self.current) != self.rows[self.current] or self._has_draft() and not preserve:
                self._show(self.current, reload=not preserve)
        elif preserve:
            self._sync_selection()
            self.selected_label.set(self.current+' · 当前拓扑未使用 · 资料草稿待应用')
            self._write_detail('器件资料可随工程保存，当前拓扑没有此器件的应力结果。')
        elif self.rows and not self._selection_cleared:
            self._show(next(iter(self.rows)))
            self._sync_selection()
        else:
            self._clear_editor()

    def mark_stale(self):
        """Invalidate displayed verdicts immediately without discarding drafts."""
        if self._stale:
            return
        self._stale = True
        for ref in self.tree.get_children():
            self.tree.set(ref,'status','待重新计算')
            self.tree.item(ref, tags=('stale',))
        if self._view_button is not None:
            self._view_button.state(['disabled'])
        self.summary.set('待重新计算 · 电气参数已变化，旧初筛结果已失效。')
        if self.current in self.rows:
            self.selected_label.set(self.current+' · '+self.rows[self.current]['role']+' · 待重新计算')
        self._write_detail('当前参数尚无有效应力结果，等待计算。')

    def _candidate_item(self):
        item = {key:var.get().strip() for key,var in self.draft.items()}
        for key in RATING_FIELDS:
            text = item[key]
            try: item[key] = float(text) if text else None
            except ValueError: raise ValueError('额定值请输入数字，支持 1e-3；未知请留空') from None
        item['capacitor_type'] = next(k for k,v in CAP_TYPES.items() if v==self.cap_type.get())
        return item

    def apply_item(self):
        if not self.current: return False
        try:
            candidate = copy.deepcopy(self.config_data)
            candidate['items'][self.current] = self._candidate_item()
            candidate = normalize_management(candidate)
            self.changed(candidate)
        except (ValueError,TypeError) as exc:
            messagebox.showerror('请核对器件资料',str(exc),parent=self)
            return False
        try:
            self.refresh()
        except (ValueError, tk.TclError):
            # Metadata can still be applied when the electrical form is invalid.
            self.config_data = candidate
            self.loaded_item = self._candidate_item()
            self.mark_stale()
        return True

    def _has_draft(self):
        if self.current is None or self.loaded_item is None:
            return False
        try:
            return self._candidate_item() != self.loaded_item
        except ValueError:
            return True

    def confirm_draft(self):
        if not self._has_draft():
            return True
        choice = messagebox.askyesnocancel('未应用的器件资料', '是否先应用当前器件的修改？', parent=self)
        return choice is False or (choice is True and self.apply_item())

    def discard_draft(self):
        if self.current in self.rows and self._has_draft():
            self._show(self.current)
        elif self.current is not None and self.current not in self.rows:
            self._clear_editor()

    def select(self, _event=None):
        selection = self.tree.selection()
        if not self.loading and selection and selection[0] != self.current:
            self.select_ref(selection[0], notify=True)

    def select_ref(self, ref, *, notify=False, before_commit=None):
        """Change the active designator after handling the old item's draft."""
        if self.loading or (ref is not None and ref not in self.rows):
            return False
        if ref == self.current:
            if before_commit is not None and before_commit() is False:
                return False
            self._sync_selection(reveal=True)
            return True
        self.loading = True
        try:
            if not self.confirm_draft():
                return False
            if before_commit is not None and before_commit() is False:
                return False
            if notify and self.on_select is not None and self.on_select(ref) is False:
                return False
            self._selection_cleared = ref is None
            if ref is None:
                self._clear_editor()
            else:
                self._show(ref)
            return True
        finally:
            self._sync_selection(reveal=True)
            self.loading = False

    def _sync_selection(self, *, reveal=False):
        selected = self.tree.selection()
        if self.current in self.rows:
            if selected != (self.current,):
                self.tree.selection_set(self.current)
            if reveal:
                self.tree.focus(self.current)
                self.tree.see(self.current)
        elif selected:
            self.tree.selection_remove(*selected)

    def _clear_editor(self):
        self.current = None
        self.loaded_item = None
        for key, var in self.draft.items():
            var.set('')
            self.editors[key].configure(state='disabled')
        self.cap_type.set(CAP_TYPES['unknown'])
        self.cap_select.configure(state='disabled')
        self._apply_button.configure(state='disabled')
        if self._view_button is not None:
            self._view_button.state(['disabled'])
        self.selected_label.set('选择一行，查看或编辑器件资料。')
        self._layout_form()
        self._write_detail('')

    def _write_detail(self, text):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text)
        self.detail.configure(state='disabled')

    def _show(self, ref, reload=True):
        self.current = ref
        row = self.rows[ref]
        self.voltage_caption.set('MOS Vds / V' if row['kind']=='mos' else '二极管 Vrrm / V' if row['kind']=='diode' else '电容耐压 / V')
        if reload:
            for key,var in self.draft.items():
                val = row.get(key)
                var.set('' if val is None else f'{val:g}' if isinstance(val,(int,float)) else val)
            self.cap_type.set(CAP_TYPES.get(row.get('capacitor_type'), CAP_TYPES['unknown']))
            self.loaded_item = self._candidate_item()
        for key in TEXT_FIELDS:
            self.editors[key].configure(state='normal')
        self._apply_button.configure(state='normal')
        if self._view_button is not None:
            self._view_button.state(['disabled' if self._stale else '!disabled'])
        for key in RATING_FIELDS:
            enabled = key in RATINGS_BY_KIND.get(row['kind'], ())
            self.editors[key].configure(state='normal' if enabled else 'disabled')
        self.cap_select.configure(state='readonly' if row['kind']=='capacitor' else 'disabled')
        self._layout_form()
        if self._stale:
            self.selected_label.set(ref+' · '+row['role']+' · 待重新计算')
            self._write_detail('当前参数尚无有效应力结果，等待计算。')
            return
        self.selected_label.set(ref+' · '+row['role']+' · '+row['status'])
        lines = ['\n'.join(filter(None, (check_text(check), check['source'], check['note'])))
                 for check in row['checks']]
        if row['identity_missing']:
            lines.insert(0, '待补资料 · ' + '、'.join(row['identity_missing']))
        if not row['checks']:
            lines.append('证据范围 · 此项用于记录器件资料。')
        self._write_detail('\n\n'.join(lines))

    def edit_policy(self):
        win = tk.Toplevel(self); win.title('降额规则与依据'); win.transient(self.winfo_toplevel())
        win.geometry('900x710'); win.minsize(760,650)
        body = ttk.Frame(win,padding=12); body.pack(fill='both',expand=True)
        body.columnconfigure(1,weight=1)
        ttk.Label(body,text=SOURCE_NOTE,wraplength=840).grid(row=0,column=0,columnspan=4,sticky='ew',pady=5)
        zone = tk.StringVar(value=self.config_data['zone'])
        ttk.Label(body,text='适用分区（按所用规范选择）').grid(row=1,column=0,sticky='w')
        ttk.Combobox(body,textvariable=zone,values=('I','II'),state='readonly',width=8).grid(row=1,column=1,sticky='w')
        ttk.Label(body,text='规则').grid(row=2,column=0,sticky='w')
        ttk.Label(body,text='I / II 区允许使用率').grid(row=2,column=1,sticky='w')
        ttk.Label(body,text='自定义 / %（留空沿用规范）').grid(row=2,column=2,sticky='w')
        variables = {}
        for i,(key,rule) in enumerate(RULES.items(),3):
            ttk.Label(body,text=rule[0]).grid(row=i,column=0,sticky='w',pady=3)
            ttk.Label(body,text=' / '.join('未列' if x is None else f'{x:.0%}' for x in rule[1:3])).grid(row=i,column=1,sticky='w')
            variables[key] = tk.StringVar(value='' if key not in self.config_data['overrides'] else f"{100*self.config_data['overrides'][key]:g}")
            ttk.Entry(body,textvariable=variables[key],width=12).grid(row=i,column=2,sticky='w')
        r = 3+len(RULES)
        ttk.Label(body,text='自定义依据 / 原因').grid(row=r,column=0,sticky='w',pady=8)
        reason = tk.StringVar(value=self.config_data['override_reason'])
        ttk.Entry(body,textvariable=reason).grid(row=r,column=1,columnspan=2,sticky='ew')
        ttk.Label(body, text='MOS 尖峰宽度小于 min(1 µs, Ts/50) 时可按窄尖峰规则。其他情况沿用稳态降额。'
                             '尖峰宽度或反向电压缺少模型时列为待复核。', wraplength=720,
                  justify='left').grid(row=r+1,column=0,columnspan=3,sticky='ew',pady=8)
        def apply():
            try:
                candidate = copy.deepcopy(self.config_data)
                candidate.update(zone=zone.get(),override_reason=reason.get(),overrides={k:float(v.get())/100 for k,v in variables.items() if v.get().strip()})
                candidate = normalize_management(candidate)
                self.changed(candidate); self.refresh(preserve=True); win.destroy()
            except (ValueError,TypeError) as exc: messagebox.showerror('规则无效',str(exc),parent=win)
        buttons = ttk.Frame(body); buttons.grid(row=r+2,column=0,columnspan=3,sticky='e',pady=8)
        ttk.Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=6)
        ttk.Button(buttons,text='应用规则',command=apply).pack(side='right')
