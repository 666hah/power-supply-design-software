"""Small desktop LDO editor; shares all equations and reports with the web UI."""
import copy
import tkinter as tk
from tkinter import ttk, filedialog, font, messagebox
from ldo import normalize,calculate,FIELDS,OPTIONAL
from ldo_report import fmt,STATE

CHOICES={'output_mode':{'fixed':'固定输出','adjustable':'可调输出（计算分压）'},
         'reverse_blocking':{'unknown':'待核对','yes':'具备（按芯片条件）','no':'不具备'}}

BG, INK, MUTED, BLUE = '#f1f5f9', '#102238', '#526987', '#1469d8'


class LdoDesigner:
    def __init__(self, root, initial_config=None, on_return=None, *, container=None):
        self.root = root
        self.container = container if container is not None else root
        self.on_return = on_return
        self._embedded = container is not None
        self.spec = normalize(initial_config)
        self.result = None
        self.vars = {}
        self.items = {}
        self._field_labels = []
        self._field_groups = []
        self._result_pages = {}
        self._table_headers = {}
        from ui_preferences import font_size

        if not self._embedded:
            from software_architecture_ui import add_architecture_menu
            from project_identity import GITHUB_LABEL, add_github_menu_item, open_github

            root.title('LDO 线性稳压器设计')
            root.geometry('1320x850')
            root.minsize(1000, 650)
            ttk.Style(root).theme_use('clam')
            menubar = tk.Menu(root)
            add_architecture_menu(menubar, root)
            help_menu = tk.Menu(menubar, tearoff=False)
            add_github_menu_item(help_menu, root)
            menubar.add_cascade(label='帮助', menu=help_menu)
            root.configure(menu=menubar)
            root.protocol('WM_DELETE_WINDOW', self.close)

        self._body_font = font.Font(root=root, family='Microsoft YaHei UI', size=-14)
        self._section_font = font.Font(root=root, family='Microsoft YaHei UI', size=-14, weight='bold')
        self._heading_font = font.Font(root=root, family='Microsoft YaHei UI', size=-20, weight='bold')
        self.set_font_size(font_size())
        style = ttk.Style(root)
        style.configure('Ldo.TFrame', background=BG)
        style.configure('LdoCard.TFrame', background='white')
        style.configure('Ldo.TLabel', foreground=INK, background='white', font=self._body_font)
        style.configure('LdoMuted.TLabel', foreground=MUTED, background='white', font=self._body_font)
        style.configure('LdoSection.TLabel', foreground=BLUE, background='white', font=self._section_font)
        style.configure('LdoConclusion.TLabel', foreground=INK, background='#eaf2fb', font=self._section_font)
        style.configure('LdoTitle.TLabel', foreground=INK, background='white', font=self._heading_font)
        style.configure('Ldo.TButton', foreground=INK, background='white', bordercolor='#cedbea',
                        padding=(11, 6), font=self._body_font)
        style.map('Ldo.TButton', background=[('active', '#e7f0ff')])
        style.configure('Ldo.TCheckbutton', foreground=INK, background='white', font=self._body_font)
        style.configure('Ldo.TEntry', padding=5, bordercolor='#cedbea', fieldbackground='white')
        style.configure('Ldo.TCombobox', padding=5, bordercolor='#cedbea')
        style.configure('Ldo.Treeview', font=self._body_font, background='white', fieldbackground='white')
        style.configure('Ldo.Treeview.Heading', font=self._section_font, foreground=INK,
                        background='#edf3fa', padding=(6, 5))
        style.configure('Ldo.TNotebook', background=BG, borderwidth=0)
        style.configure('Ldo.TNotebook.Tab', padding=(12, 7), font=self._body_font)
        style.map('Ldo.TNotebook.Tab', foreground=[('selected', BLUE)])

        self.frame = ttk.Frame(self.container, padding=(16, 12), style='Ldo.TFrame')
        self.frame.pack(fill='both', expand=True)
        head = ttk.Frame(self.frame, padding=(14, 8), style='LdoCard.TFrame')
        head.pack(fill='x', pady=(0, 10))
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text='LDO 线性稳压器', style='LdoTitle.TLabel').grid(row=0, column=0, sticky='w')
        if not self._embedded:
            ttk.Button(head, text='重新计算', command=self.compute, style='Ldo.TButton').grid(row=0, column=1, sticky='e')
            if on_return:
                ttk.Button(head, text='返回系统架构', command=self.close, style='Ldo.TButton').grid(row=0, column=2, padx=(8, 0))
            ttk.Button(head, text=GITHUB_LABEL, command=lambda: open_github(root),
                       style='Ldo.TButton').grid(row=0, column=3, padx=(8, 0))
        self.status = tk.StringVar(value='待计算 · 结果按静态线性模型评估。')
        conclusion = ttk.Label(head, textvariable=self.status, style='LdoConclusion.TLabel',
                               justify='left', padding=(8, 5))
        conclusion.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(6, 0))
        conclusion.bind('<Configure>', lambda event: conclusion.configure(wraplength=max(1, event.width-16)))
        split = ttk.Panedwindow(self.frame, orient='horizontal')
        split.pack(fill='both', expand=True)
        left = ttk.Frame(split, style='LdoCard.TFrame')
        split.add(left, weight=1)
        canvas = tk.Canvas(left, width=350, highlightthickness=0, background='white')
        scroll = ttk.Scrollbar(left, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        form = ttk.Frame(canvas, padding=(12, 6), style='LdoCard.TFrame')
        win = canvas.create_window((0, 0), window=form, anchor='nw')
        form.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        def resize_form(event):
            canvas.itemconfigure(win, width=event.width)
            wrap = max(90, int(event.width*.45)-16)
            for label in self._field_labels:
                label.configure(wraplength=wrap)
        canvas.bind('<Configure>', resize_form)

        basic = self.group(form, '器件与控制')
        for k, label in [('manufacturer', '制造商'), ('model', '型号'), ('package', '封装'), ('notes', '资料来源与条件')]:
            self.field(basic, k, label)
        self.choice(basic, 'output_mode', '输出类型')
        self.choice(basic, 'reverse_blocking', '反向电流保护')
        for k,label in [('follow_input','跟随上游电压'),('thermal_verified','热阻已按 PCB 核对'),
                        ('enable_pin','具有 EN 引脚'),('power_good','具有 PG 引脚')]:
            value = tk.BooleanVar(value=self.spec[k])
            self.vars[k] = (value, 1)
            ttk.Checkbutton(form, text=label, variable=value, style='Ldo.TCheckbutton').pack(anchor='w', pady=3)
        self.adjustable_frame = None
        for section, fields in FIELDS:
            group = self.group(form, section)
            if section == '可调输出分压':
                self.adjustable_frame = group
            for k, label, unit, scale in fields:
                self.field(group, k, label, unit, scale)
        self.bind_form_scroll(canvas, canvas)

        right = ttk.Frame(split, style='Ldo.TFrame', padding=(8, 0, 0, 0))
        split.add(right, weight=3)
        self.book = ttk.Notebook(right, style='Ldo.TNotebook')
        self.corner = self.tree('corners', '关键结果', ['工况','输入电压 / V','输出电流 / A','压差裕量 / V','芯片损耗 / W','效率 / %','结温 / °C'])
        self.checks = self.tree('checks', '规格与降额', ['检查项','计算值','限值','状态','判定依据'])
        bom = ttk.Frame(self.book, padding=12, style='LdoCard.TFrame')
        self.book.add(bom, text='器件 BOM')
        self._result_pages['bom'] = bom
        ttk.Label(bom, text='电容与分压电阻', style='LdoSection.TLabel').pack(anchor='w')
        bom_body = ttk.Frame(bom, style='LdoCard.TFrame')
        bom_body.pack(fill='both', expand=True)
        bom_view = tk.Canvas(bom_body, background='white', highlightthickness=0)
        bom_scroll = ttk.Scrollbar(bom_body, command=bom_view.yview)
        bom_view.configure(yscrollcommand=bom_scroll.set)
        bom_scroll.pack(side='right', fill='y')
        bom_view.pack(side='left', fill='both', expand=True)
        self.bom_form = ttk.Frame(bom_view, style='LdoCard.TFrame')
        self.bom_frames = {}
        bom_window = bom_view.create_window((0, 0), window=self.bom_form, anchor='nw')
        self.bom_form.bind('<Configure>', lambda event: bom_view.configure(scrollregion=bom_view.bbox('all')))
        def resize_bom(event):
            bom_view.itemconfigure(bom_window, width=event.width)
            self.bom_note.configure(wraplength=max(100, event.width-12))
        bom_view.bind('<Configure>', resize_bom)
        self.draw_bom()
        self.bind_form_scroll(bom_view, bom_view)
        self.vars['output_mode'][0].trace_add('write',lambda *args:self.update_mode());self.update_mode()
        notes = ttk.Frame(right, style='LdoCard.TFrame')
        ttk.Label(notes, text='计算条件', style='LdoSection.TLabel').pack(anchor='w', padx=9, pady=(7, 0))
        content = ttk.Frame(notes, style='LdoCard.TFrame')
        content.pack(fill='x')
        self.info = tk.Text(content, height=3, wrap='word', font=self._body_font, background='white',
                            foreground=INK, relief='flat', padx=9, pady=5)
        info_scroll = ttk.Scrollbar(content, command=self.info.yview)
        self.info.configure(yscrollcommand=info_scroll.set)
        info_scroll.pack(side='right', fill='y')
        self.info.pack(side='left', fill='x', expand=True)
        if not self._embedded:
            bar = ttk.Frame(right, style='Ldo.TFrame')
            bar.pack(side='bottom', fill='x', pady=(8, 0))
            for kind in ('docx', 'xlsx', 'json'):
                ttk.Button(bar, text='导出 '+kind.upper(), command=lambda k=kind:self.report(k),
                           style='Ldo.TButton').pack(side='left', padx=(0, 8))
        notes.pack(side='bottom', fill='x', pady=(8, 0))
        self.book.pack(fill='both', expand=True)
        self.compute()

    def set_font_size(self, size):
        self._body_font.configure(size=-size)
        self._section_font.configure(size=-size)
        self._heading_font.configure(size=-min(32, round(size*1.43)))
        ttk.Style(self.root).configure('Ldo.Treeview', rowheight=max(26, self._body_font.metrics('linespace')+8))
        self._unit_width = max(self._body_font.measure(unit) for _, fields in FIELDS for _, _, unit, _ in fields)+7
        for group in self._field_groups:
            group.columnconfigure(2, minsize=self._unit_width)
        for table in self._table_headers:
            self._fit_table_columns(table)

    def bind_form_scroll(self, canvas, widget):
        def scroll(event):
            canvas.yview_scroll(-int(event.delta/120), 'units')
            return 'break'

        widget.bind('<MouseWheel>', scroll, add='+')
        for child in widget.winfo_children():
            self.bind_form_scroll(canvas, child)

    def group(self, parent, title):
        group = ttk.Frame(parent, style='LdoCard.TFrame')
        group.columnconfigure(0, weight=2, uniform='field')
        group.columnconfigure(1, weight=2, uniform='field')
        group.columnconfigure(2, minsize=self._unit_width)
        self._field_groups.append(group)
        group.pack(fill='x', pady=(6, 4))
        ttk.Label(group, text=title, style='LdoSection.TLabel').grid(row=0, column=0, columnspan=3, sticky='w', pady=(5, 4))
        return group

    def layout_field(self, parent, label, control, unit):
        row = parent.grid_size()[1]
        title = ttk.Label(parent, text=label, style='Ldo.TLabel', wraplength=145)
        title.grid(row=row, column=0, sticky='ew', padx=(0, 8), pady=4)
        self._field_labels.append(title)
        control.grid(row=row, column=1, columnspan=1 if unit else 2, sticky='ew', pady=4)
        if unit:
            ttk.Label(parent, text=unit, style='LdoMuted.TLabel').grid(row=row, column=2, sticky='w', padx=(7, 0))

    def field(self, parent, key, label, unit='', scale=1):
        value = self.spec.get(key)
        variable = tk.StringVar(value='' if value is None else str(value/scale) if isinstance(value, (int,float)) else value)
        self.vars[key] = (variable, scale)
        control = ttk.Entry(parent, textvariable=variable, width=8, font=self._body_font, style='Ldo.TEntry')
        self.layout_field(parent, label, control, unit)

    def choice(self, parent, key, label):
        variable = tk.StringVar(value=CHOICES[key][self.spec[key]])
        self.vars[key] = (variable, 1)
        control = ttk.Combobox(parent, textvariable=variable, values=list(CHOICES[key].values()), width=10,
                               state='readonly', font=self._body_font, style='Ldo.TCombobox')
        self.layout_field(parent, label, control, '')

    def update_mode(self):
        active=self.vars['output_mode'][0].get() in ('adjustable',CHOICES['output_mode']['adjustable'])
        if active:self.adjustable_frame.pack(fill='x')
        else:self.adjustable_frame.pack_forget()
        for ref in ('R1','R2'):
            if active:self.bom_frames[ref].pack(fill='x',pady=5,before=self.bom_note)
            else:self.bom_frames[ref].pack_forget()

    def tree(self, key, title, headers):
        frame = ttk.Frame(self.book, style='LdoCard.TFrame')
        self.book.add(frame, text=title)
        self._result_pages[key] = frame
        table = ttk.Treeview(frame, columns=list(range(len(headers))), show='headings', style='Ldo.Treeview')
        ybar = ttk.Scrollbar(frame, command=table.yview)
        xbar = ttk.Scrollbar(frame, orient='horizontal', command=table.xview)
        table.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        table.grid(row=0, column=0, sticky='nsew')
        ybar.grid(row=0, column=1, sticky='ns')
        xbar.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for column, label in enumerate(headers):
            table.heading(column, text=label)
            table.column(column, anchor='w' if label in ('检查项', '判定依据') else 'center')
        self._table_headers[table] = tuple(headers)
        self._fit_table_columns(table)
        table.tag_configure('review', background='#fff3df')
        return table

    def _fit_table_columns(self, table):
        for column, label in enumerate(self._table_headers[table]):
            minimum = self._section_font.measure('低线 · 满载' if label == '工况' else label) + 18
            target = {'判定依据': 230, '检查项': 126}.get(label, 88)
            table.column(column, width=max(minimum, target), minwidth=minimum)

    def selected_result_page(self):
        selected = self.book.select()
        return next((key for key, frame in self._result_pages.items() if selected == str(frame)), None)

    def restore_result_page(self, key):
        frame = self._result_pages.get(key)
        if frame is not None:
            self.book.select(frame)

    def draw_bom(self):
        for ref in ('C_IN1','C_OUT1','R1','R2'):
            card = ttk.Frame(self.bom_form, style='LdoCard.TFrame', padding=(0, 6))
            card.pack(fill='x', pady=5)
            self.bom_frames[ref] = card
            self.items[ref] = {}
            saved = self.spec['component_management']['items'].get(ref, {})
            is_capacitor = ref.startswith('C_')
            rating = ('voltage_V', '耐压 / V') if is_capacitor else ('power_W', '额定功率 / W')
            ttk.Label(card, text=ref, style='LdoSection.TLabel').grid(row=0, column=0, columnspan=4, sticky='w')
            for column, (key, label) in enumerate([('manufacturer','厂家'), ('model','型号'), ('package','封装'), rating]):
                ttk.Label(card, text=label, style='Ldo.TLabel').grid(row=1, column=column, sticky='w', pady=(6, 3))
                variable = tk.StringVar(value=saved.get(key) or '')
                self.items[ref][key] = variable
                ttk.Entry(card, textvariable=variable, width=7, font=self._body_font, style='Ldo.TEntry').grid(
                    row=2, column=column, sticky='ew', padx=(0, 8))
                card.columnconfigure(column, weight=1)
            if is_capacitor:
                variable = tk.StringVar(value=saved.get('capacitor_type', 'unknown'))
                self.items[ref]['capacitor_type'] = variable
                ttk.Label(card, text='电容类型', style='Ldo.TLabel').grid(row=3, column=0, sticky='w', pady=5)
                ttk.Combobox(card, textvariable=variable, values=['unknown','mlcc','electrolytic','film','other'],
                             state='readonly', width=10, font=self._body_font, style='Ldo.TCombobox').grid(
                                 row=3, column=1, columnspan=2, sticky='ew', padx=(0, 8), pady=5)
        self.bom_note = ttk.Label(self.bom_form, text='可调输出的 R2 自动计算，电阻按 20% 额定功率初查。有效电容与 ESR 在左侧填写。',
                                  style='LdoMuted.TLabel', wraplength=600)
        self.bom_note.pack(fill='x', pady=8)

    def _config_dict(self):
        p=copy.deepcopy(self.spec)
        for k,(var,scale) in self.vars.items():
            text=var.get()
            if k in CHOICES:p[k]=next((key for key,label in CHOICES[k].items() if label==text),text)
            elif k in ('manufacturer','model','package','notes'):p[k]=text
            elif isinstance(text,bool):p[k]=text
            else:p[k]=None if text=='' and k in OPTIONAL else float(text)*scale
        for ref,fields in self.items.items():
            item=p['component_management']['items'].setdefault(ref,{})
            for key,v in fields.items():item[key]=(float(v.get()) if v.get() else None) if key in ('voltage_V','power_W') else v.get()
        return normalize(p)

    def compute(self):
        try:
            result = calculate(self._config_dict())
            self.spec, self.result = result['spec'], result
            for tree in (self.corner, self.checks):
                tree.delete(*tree.get_children())
            for case in result['corners']:
                efficiency = case['eta']*100 if case['eta'] is not None else None
                endpoint, load = case['id'].split('_', 1)
                caption = ('低线' if endpoint == 'Vinmin' else '高线') + f' · {load}'
                self.corner.insert('', 'end', values=(caption, fmt(case['V_in']), fmt(case['I_out']),
                    fmt(case['dropout_margin']), fmt(case['P_chip']), fmt(efficiency), fmt(case['T_j'])),
                    tags=() if case['regulated'] else ('review',))
            for check in result['checks']:
                value = f"{fmt(check['value'])} {check['unit']}".rstrip() if check['value'] is not None else '—'
                limit = f"{check['comparison']} {fmt(check['limit'])}" if check['limit'] is not None else '—'
                self.checks.insert('', 'end', values=(check['name'], value, limit, STATE[check['state']], check['note']),
                                   tags=() if check['state']=='pass' else ('review',))
            divider = f"分压下臂 R2 = {fmt(result['divider']['R_bottom'])} Ω" if self.spec['output_mode']=='adjustable' else '固定输出型由芯片设定。'
            self.info.configure(state='normal')
            self.info.delete('1.0', 'end')
            self.info.insert('end', '\n'.join((*result['notes'], divider)))
            self.info.configure(state='disabled')
            margin = min(case['dropout_margin'] for case in result['corners'])
            key_result = f'最小压差裕量 {fmt(margin)} V'
            if result['worst']['T_j'] is not None:
                key_result += f" · 最高估算结温 {fmt(result['worst']['T_j'])} °C"
            self.status.set(f"结论 · {STATE[result['state']]}（静态模型）\n关键结果 · {key_result}")
            return True
        except Exception as e:
            self.status.set('待重新计算 · 请检查当前 LDO 参数。')
            messagebox.showerror('LDO 参数', str(e), parent=self.root)
            return False

    def report(self,kind):
        if not self.compute():return
        path=filedialog.asksaveasfilename(parent=self.root,initialfile='LDO设计报告.'+kind,defaultextension='.'+kind,filetypes=[(kind.upper(),'*.'+kind)])
        if path:
            try:
                from ldo_report import export_report
                export_report(self.result, path)
                self.status.set(self.status.get() + f'\n已导出 · {kind.upper()}')
            except Exception as e:messagebox.showerror('LDO 报告',str(e),parent=self.root)

    def export_report(self):
        """Default report command when hosted by the system workspace."""
        self.report('docx')

    def close(self):
        if self.on_return and self.on_return(self) is False:
            return
        if not self._embedded:
            self.root.destroy()
