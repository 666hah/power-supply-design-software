"""Compact virtual rows: editing many capacitors does not create many Tk fields."""
import copy
import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk
from capacitor_banks import output_ref, validate
from capacitor_impedance import CURVE_FIELD, MODE_FIELD, THERMAL_FIELD, active_curve


def _frequency_label(value):
    for scale, unit in ((1e9, 'GHz'), (1e6, 'MHz'), (1e3, 'kHz')):
        if value >= scale:
            return f'{value / scale:.4g} {unit}'
    return f'{value:.4g} Hz'


class BankEditor(ttk.Frame):
    def __init__(self,parent,values,changed=lambda:None,*,rail=0):
        super().__init__(parent)
        self.changed=changed;self.index=0;self.busy=False
        self.rail=rail
        self.values=validate(values)
        self.columnconfigure(0,weight=1)
        top=ttk.Frame(self);top.grid(row=0,column=0,sticky='ew')
        ttk.Label(top,text='电容数量').pack(side='left')
        self.count=tk.StringVar(value=str(len(self.values)))
        ttk.Spinbox(top,from_=1,to=1000,textvariable=self.count,width=5).pack(side='left',padx=4)
        ttk.Button(top,text='设置数量',command=self.resize).pack(side='left')
        self.tree=ttk.Treeview(self,columns=('C','ESR','ESL'),show='tree headings',height=4,selectmode='browse')
        self.tree.heading('#0',text='序号');self.tree.column('#0',width=37,stretch=False)
        for key,unit in (('C','µF'),('ESR','mΩ'),('ESL','nH')):
            self.tree.heading(key,text=key+' / '+unit);self.tree.column(key,width=73,minwidth=47)
        self.tree.grid(row=1,column=0,sticky='ew',pady=3)
        bar=ttk.Scrollbar(self,orient='vertical',command=self.tree.yview);bar.grid(row=1,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=bar.set)
        form=ttk.Frame(self);form.grid(row=2,column=0,sticky='ew')
        self.variables={k:tk.StringVar() for k in ('C','ESR','ESL')}
        for j,(key,unit) in enumerate((('C','µF'),('ESR','mΩ'),('ESL','nH'))):
            ttk.Label(form,text=key+' / '+unit).grid(row=0,column=j)
            entry=ttk.Entry(form,textvariable=self.variables[key],width=9)
            entry.grid(row=1,column=j,sticky='ew',padx=2);form.columnconfigure(j,weight=1)
            entry.bind('<KeyRelease>',lambda _e:self.changed())
            entry.bind('<FocusOut>',lambda _e:self.commit())
        actions=ttk.Frame(self);actions.grid(row=3,column=0,sticky='ew',pady=3)
        actions.columnconfigure((0, 1), weight=1)
        ttk.Button(actions,text='增加一颗',command=self.add).grid(row=0,column=0,sticky='ew')
        ttk.Button(actions,text='删除选中',command=self.remove).grid(row=0,column=1,sticky='ew',padx=(4,0))
        self.data_button = ttk.Button(self, text='选中电容的阻抗曲线与热阻…', command=self.open_curve_data)
        self.data_button.grid(row=4,column=0,sticky='ew',pady=(1,3))
        self._hint = '选中行修改。同一端口的电容全部并联。'
        self.note=tk.StringVar(value=self._hint)
        hint = ttk.Label(self,textvariable=self.note,wraplength=300)
        hint.grid(row=5,column=0,sticky='ew')
        hint.bind('<Configure>',lambda e:hint.configure(wraplength=max(140,e.width-8)))
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.load(self.values)

    def load(self,values):
        self.busy=True;self.values=validate(values);self.index=0
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(self.values):
            self.tree.insert('', 'end',iid=str(i),text=str(i+1),values=self.display(row))
        self.count.set(str(len(self.values)));self.tree.selection_set('0');self.populate();self.busy=False

    @staticmethod
    def display(row):return tuple(f'{row[k]/scale:.10g}' for k,scale in (('C',1e-6),('ESR',1e-3),('ESL',1e-9)))

    def populate(self):
        for k,v in zip(self.variables,self.display(self.values[self.index])):self.variables[k].set(v)
        self.note.set(self._hint)

    def commit(self,strict=False):
        try:
            old = self.values[self.index]
            updates = {}
            for (key, scale), shown in zip((('C', 1e-6), ('ESR', 1e-3), ('ESL', 1e-9)), self.display(old)):
                entered = self.variables[key].get()
                if entered != shown:
                    updates[key] = float(entered) * scale
            if updates:
                row = validate([{**old, **updates}])[0]
                self.values[self.index] = row
                self.tree.item(str(self.index), values=self.display(row))
            self.note.set(self._hint)
            return True
        except (ValueError,tk.TclError) as exc:
            self.note.set(str(exc))
            if strict:raise ValueError(str(exc)) from exc
            return False

    def select(self,_event=None):
        if self.busy or not self.tree.selection():return
        new=int(self.tree.selection()[0])
        if new==self.index:return
        if not self.commit():
            self.tree.selection_set(str(self.index));return
        self.index=new;self.populate()

    def get(self):
        self.commit(True)
        return copy.deepcopy(self.values)

    def resize(self):
        try:
            count=int(self.count.get())
            if count<1:raise ValueError('至少保留一颗电容')
            rows=self.get();rows=(rows+[copy.deepcopy(rows[-1]) for _ in range(max(0,count-len(rows)))])[:count]
            self.load(rows);self.changed()
        except ValueError as exc:self.note.set(str(exc))

    def add(self):self.count.set(str(len(self.values)+1));self.resize()

    def remove(self):
        if len(self.values)==1:self.note.set('至少保留一颗电容');return
        rows=copy.deepcopy(self.values);rows.pop(self.index);self.load(rows);self.changed()

    def reference(self, index):
        return f'C_IN{index+1}' if self.rail is None else output_ref(self.rail or 1,index+1,bool(self.rail))

    def open_curve_data(self):
        if self.commit():
            return ImpedanceDialog(self, self.index, self.reference(self.index))

    def set_impedance_mode(self, index, mode):
        data = self.values[index]
        if mode == ('curve' if active_curve(data) else 'fixed'):
            return
        self.values[index] = validate([dict(data, **{MODE_FIELD: mode})])[0]
        self.changed()

    def apply_impedance(self, index, curve, thermal_text):
        """Apply to the selected row only, after validating the complete draft."""
        data = dict(self.values[index])
        if curve is None and active_curve(data):
            raise ValueError('请先在「器件模型精度选择」改为固定参数 RLC，再移除曲线。')
        thermal_text = thermal_text.strip()
        if thermal_text:
            try:
                thermal = float(thermal_text)
            except ValueError as exc:
                raise ValueError('热阻请填写正数，留空时仅计算耗散功率') from exc
            data[THERMAL_FIELD] = thermal
        else:
            data.pop(THERMAL_FIELD, None)
        if curve is None:
            data.pop(CURVE_FIELD, None)
        else:
            data[CURVE_FIELD] = curve
            if not active_curve(self.values[index]):
                data[MODE_FIELD] = 'fixed'
        row = validate([data])[0]
        if row != self.values[index]:
            self.values[index] = row
            self.changed()


class CapacitorModelPicker(ttk.LabelFrame):
    """Select the physical capacitor in the centralized device-model panel."""

    def __init__(self, parent, banks):
        super().__init__(parent, text='输入与输出电容', padding=6)
        self.banks = banks
        self._editor = None
        self._device_keys = None
        self.columnconfigure(1, weight=1)
        self.port = ttk.Combobox(self, state='readonly', width=15)
        self.device = ttk.Combobox(self, state='readonly', width=15)
        for index, (label, picker) in enumerate((('端口', self.port), ('位号', self.device))):
            ttk.Label(self, text=label).grid(row=index, column=0, sticky='w', padx=(0, 6), pady=2)
            picker.grid(row=index, column=1, sticky='ew', pady=2)
            picker.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        self.model = ttk.Combobox(self, state='readonly', width=15)
        ttk.Label(self, text='模型').grid(row=2, column=0, sticky='w', padx=(0, 6), pady=2)
        self.model.grid(row=2, column=1, sticky='ew', pady=2)
        self.model.bind('<<ComboboxSelected>>', self.choose_mode)
        self.status = tk.StringVar()
        note = ttk.Label(self, textvariable=self.status, style='Muted.TLabel', wraplength=300)
        note.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(3, 0))
        note.bind('<Configure>', lambda e: note.configure(wraplength=max(140, e.width - 8)))

    def refresh(self):
        banks = self.banks()
        if not banks:
            return
        ports = tuple(banks)
        if self.port.cget('values') != ports:
            self.port.configure(values=ports)
        if self.port.get() not in banks:
            self.port.current(0)
        port = self.port.get()
        self._editor = banks[port]
        keys = (port, len(self._editor.values))
        if keys != self._device_keys:
            refs = tuple(self._editor.reference(i) for i in range(keys[1]))
            previous = self.device.get()
            self.device.configure(values=refs)
            self.device.set(previous if previous in refs else refs[0])
            self._device_keys = keys
        row = self._editor.values[self.device.current()]
        curve = row.get(CURVE_FIELD)
        self.model.configure(values=('固定参数 RLC', '阻抗曲线') if curve else ('固定参数 RLC',))
        self.model.current(1 if active_curve(row) else 0)
        text = '曲线数据已就绪' if curve else '在对应电容组导入数据后可选择阻抗曲线。'
        if text != self.status.get():
            self.status.set(text)

    def choose_mode(self, _event=None):
        if self._editor is None or self.model.current() < 0:
            return None
        mode = 'curve' if self.model.current() == 1 else 'fixed'
        self._editor.set_impedance_mode(self.device.current(), mode)
        self.refresh()


class ImpedanceDialog(tk.Toplevel):
    """Edit one embedded sweep; import is previewed before applying it."""

    def __init__(self, editor, index, reference):
        owner = editor.winfo_toplevel()
        super().__init__(owner)
        self.title(f'{reference} · 阻抗曲线与热阻')
        self.transient(owner)
        self.editor = editor
        self.index = index
        row = editor.values[index]
        self.curve = copy.deepcopy(row.get(CURVE_FIELD))
        self.curve_in_use = bool(active_curve(row))
        self.thermal = tk.StringVar(value=str(row.get(THERMAL_FIELD, '')))
        self.status = tk.StringVar()
        self.error = tk.StringVar()

        content = ttk.Frame(self, padding=14)
        content.pack(fill='both', expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(4, weight=1)
        width = min(700, self.winfo_screenwidth()-70)
        height = min(606, self.winfo_screenheight()-116)
        self.geometry(f'{width}x{height}')
        self.minsize(min(width, 540), min(height, 500))
        mode = '阻抗曲线。移除前请在「器件模型精度选择」切换为固定参数。' if self.curve_in_use else '固定参数。曲线在「器件模型精度选择」启用。'
        ttk.Label(content,text=f'当前模型 · {mode}',wraplength=width-38).grid(row=0,column=0,sticky='ew')
        toolbar = ttk.Frame(content)
        toolbar.grid(row=2,column=0,sticky='ew',pady=(8,4))
        ttk.Button(toolbar,text='导入 / 替换曲线…',command=self.import_curve).pack(side='left')
        self.clear_button = ttk.Button(toolbar,text='移除曲线',command=self.clear_curve)
        self.clear_button.pack(side='left',padx=(8,0))
        summary = ttk.Label(content, textvariable=self.status, wraplength=width-38, justify='left')
        summary.grid(row=3,column=0,sticky='ew',pady=(0,5))
        summary.bind('<Configure>', lambda e:summary.configure(wraplength=max(275,e.width-5)))

        from matplotlib.figure import Figure
        from resource_canvas import EfficientFigureCanvasTkAgg

        self.figure = Figure(figsize=(6.4, 3.2), dpi=100, layout='constrained')
        self.axes = self.figure.subplots(2, 1, sharex=True)
        self.plot = EfficientFigureCanvasTkAgg(self.figure, master=content)
        self.plot.get_tk_widget().grid(row=4,column=0,sticky='nsew')

        thermal_row = ttk.Frame(content)
        thermal_row.grid(row=5,column=0,sticky='ew',pady=(9,0))
        ttk.Label(thermal_row,text='热阻 Rθ / K/W').pack(side='left')
        ttk.Entry(thermal_row,textvariable=self.thermal,width=10).pack(side='left',padx=7)
        ttk.Label(thermal_row,text='选填。留空只算耗散，填写后估算相对环境温升。',wraplength=325).pack(side='left')
        ttk.Label(content,textvariable=self.error,wraplength=width-38,foreground='#a42b2b').grid(
            row=6,column=0,sticky='ew',pady=(4,0))
        footer = ttk.Frame(content)
        footer.grid(row=7,column=0,sticky='e',pady=(6,0))
        ttk.Button(footer,text='取消',command=self.destroy).pack(side='right')
        ttk.Button(footer,text='应用到选中电容',command=self.apply).pack(side='right',padx=(0,8))
        self.bind('<Escape>',lambda _event:self.destroy())
        self.render()
        self.grab_set()

    def import_curve(self):
        path = filedialog.askopenfilename(parent=self,title='导入电容阻抗幅相曲线',
            filetypes=[('阻抗曲线','*.csv *.tsv *.txt *.json'),('所有文件','*.*')])
        if not path:
            return False
        from capacitor_curve_io import load_curve

        try:
            self.curve = load_curve(path)
        except (OSError, ValueError) as exc:
            self.error.set(str(exc))
            return False
        self.error.set('')
        self.render()
        return True

    def clear_curve(self):
        if self.curve_in_use:
            return
        self.curve = None
        self.error.set('')
        self.render()

    def render(self):
        magnitude, phase = self.axes
        phase.set_xscale('linear')
        for axis in self.axes:
            axis.clear()
        font = {'fontfamily':'Microsoft YaHei', 'fontsize':9}
        if self.curve is None:
            self.status.set('导入频率、阻抗幅值与相位后可启用曲线计算。')
            for axis in self.axes:
                axis.set_axis_off()
            magnitude.text(.5,.31,'导入后预览阻抗幅值和相位',ha='center',va='center',transform=magnitude.transAxes,**font)
            self.clear_button.state(['disabled'])
        else:
            points = self.curve['points']
            f, z, theta = zip(*points)
            source = self.curve.get('source') or '导入曲线'
            if len(source) > 46:
                source = source[:43] + '…'
            details = '扫频带外用固定 RLC' if self.curve_in_use else '固定模型暂不使用曲线'
            self.status.set(f'{source} · {len(points)} 点\n'
                            f'{_frequency_label(f[0])} 至 {_frequency_label(f[-1])} · {details}')
            self.clear_button.state(['disabled'] if self.curve_in_use else ['!disabled'])
            magnitude.loglog(f,z,color='#226de0',marker='.' if len(f)<100 else None)
            phase.semilogx(f,theta,color='#119c83',marker='.' if len(f)<100 else None)
            magnitude.set_ylabel('|Z| / Ω', **font)
            phase.set_ylabel('相位 / °', **font)
            phase.set_xlabel('频率 / Hz', **font)
            phase.axhline(0,color='#9aa8b7',linewidth=.7)
            for axis in self.axes:
                axis.grid(True,which='major',color='#e0e8f0')
                axis.tick_params(labelsize=8)
        self.plot.draw_idle()

    def apply(self):
        try:
            self.editor.apply_impedance(self.index,self.curve,self.thermal.get())
        except ValueError as exc:
            self.error.set(str(exc))
            return False
        self.destroy()
        return True


class CapacitorResultsTable(ttk.LabelFrame):
    """Condensed per-device results from the shared capacitor snapshot."""

    _COLUMNS = (
        ('ref', '位号', 70), ('capacitance', '标称 C / µF', 105),
        ('model', '阻抗模型', 90), ('current', '纹波 RMS / A', 112),
        ('esr', '等效 ESR / mΩ', 125), ('loss', '耗散 / mW', 104),
        ('rise', '温升 / K', 96), ('coverage', '曲线覆盖', 100),
    )

    def __init__(self, parent):
        super().__init__(parent, text='电容分流与发热', padding=5)
        self.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(self, columns=[column[0] for column in self._COLUMNS],
                                 show='headings', height=4, selectmode='none')
        for key, title, width in self._COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width,
                             anchor='w' if key in ('ref', 'model') else 'e')
        self.tree.grid(row=0, column=0, sticky='nsew')
        yscroll = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll = ttk.Scrollbar(self, orient='horizontal', command=self.tree.xview)
        xscroll.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.note = ttk.Label(self, text='曲线覆盖为导入频段内纹波电流均方值占比，带外用标称 RLC。温升按耗散与热阻估算，未配置热阻显示 —。',
                              wraplength=720)
        self.note.grid(row=2, column=0, sticky='ew', pady=(5, 0))
        self.note.bind('<Configure>', lambda event: self.note.configure(wraplength=max(140, event.width - 8)))

    def refresh(self, results):
        capacitors = results['capacitors']
        outputs = results.get('outputs') or []
        rows = [(f'C_IN{index}', cap) for index, cap in enumerate(capacitors['input']['caps'], 1)]
        output_banks = ([(rail['id'], rail['capacitors']['output']['caps']) for rail in outputs]
                        if outputs else [(1, capacitors['output']['caps'])])
        for rail, bank in output_banks:
            rows.extend((output_ref(rail, index, bool(outputs)), cap) for index, cap in enumerate(bank, 1))

        def display(value, scale=1.):
            return f'{value * scale:.4g}' if value is not None else '—'

        heading_font = ttk.Style(self).lookup('Treeview.Heading', 'font') or 'TkHeadingFont'
        heading_font = tkfont.Font(root=self, font=heading_font)
        for key, title, width in self._COLUMNS:
            minimum = max(width, heading_font.measure(title) + 22)
            if self.tree.column(key, 'minwidth') != minimum:
                self.tree.column(key, width=minimum, minwidth=minimum)
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(height=min(max(len(rows), 3), 8))
        for ref, cap in rows:
            coverage = cap['curve_coverage_fraction']
            self.tree.insert('', 'end', values=(
                ref, display(cap['C'], 1e6), '阻抗曲线' if cap['impedance_model'] == 'curve' else '固定 RLC',
                display(cap['total']), display(cap['equivalent_esr_ohm'], 1e3), display(cap['loss_W'], 1e3),
                display(cap['temperature_rise_K']), f'{coverage:.1%}' if coverage is not None else '—',
            ))
