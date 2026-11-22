"""Tk architecture editor. No converter solve is run while dragging a node."""
import copy
import json
import multiprocessing
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from app_resources import resource_path
from network_layout import diode_point, scene_bounds
from project_identity import GITHUB_LABEL, add_github_menu_item, open_github

import system_workspace as model
from config_io import decode_config

BG, INK, BLUE, MUTED = '#f1f5f9', '#102238', '#1469d8', '#526987'
NAMES = {'FLYBACK': 'CCM 反激', 'QR-FLYBACK': '准谐振反激', 'BUCK': 'Buck 降压',
         'BOOST': 'Boost 升压', 'BUCK-BOOST': '反相升降压', 'ACF-FORWARD': '有源钳位正激'}
ARCHITECTURE_EXAMPLES = (
    ('分阶段电源树 · 联合启停', 'SYSTEM_STAGED_STARTUP.json'),
)
LOCAL_ARCHITECTURE = 'SYSTEM_PCS_DAB_AUX.json'


class SystemWorkspace:
    _MAX_EDITORS = 2

    def __init__(self, root, *, recovery=True):
        self.root, self.use_recovery = root, recovery
        self.project = model.fresh_project()
        self._project_baseline = None
        self.path, self.selected, self.link, self.drag, self.removal = None, None, None, None, None
        self.calculator = None
        self._editor = None
        self._editors = {}
        self._opening_unit = None
        self._unit_page_states = {}
        self._unit_detached = set()
        self._system_simulation_return = None
        self.report_process = None
        self.initialized = False
        self.zoom=1.0
        self._draw_job=None
        self._drag_dirty=False
        self._review=None
        self._edit_dirty=False
        self._commit_edit=None
        self._inspector_vars=[]
        self._panning=False
        self._toolbar_layout_job=None
        self._sequence_dialog=None
        root.title('开关电源设计 · 系统工作台')
        root.geometry(f'{min(1560, root.winfo_screenwidth()-50)}x{min(960, root.winfo_screenheight()-90)}')
        root.minsize(1000, 600)
        root.configure(bg=BG)
        from software_architecture_ui import add_architecture_menu

        menubar = tk.Menu(root)
        filemenu = tk.Menu(menubar, tearoff=False)
        filemenu.add_command(label='新建工程', command=self.new)
        filemenu.add_command(label='打开工程或导入配置…', command=self.open_file)
        filemenu.add_command(label='保存工程', command=self.save, accelerator='Ctrl+S')
        filemenu.add_command(label='另存为…', command=lambda: self.save(save_as=True))
        menubar.add_cascade(label='文件', menu=filemenu)
        add_architecture_menu(menubar, root)
        examples = tk.Menu(menubar, tearoff=False)
        alternate = (('本机工程 · 双源辅电', LOCAL_ARCHITECTURE)
                     if resource_path('examples/' + LOCAL_ARCHITECTURE).is_file()
                     else ('二极管 OR · 双源辅电', 'SYSTEM_AUX_ORING.json'))
        for label, filename in (*ARCHITECTURE_EXAMPLES, alternate):
            examples.add_command(label=label, command=lambda name=filename: self._load_architecture_example(name))
        menubar.add_cascade(label='架构示例', menu=examples)
        help_menu = tk.Menu(menubar, tearoff=False)
        add_github_menu_item(help_menu, root)
        menubar.add_cascade(label='帮助', menu=help_menu)
        self._architecture_menu = menubar
        ldo_menu = self._ldo_menu = tk.Menu(root)
        ldo_file = tk.Menu(ldo_menu, tearoff=False)
        ldo_file.add_command(label='保存工程', command=self.save, accelerator='Ctrl+S')
        ldo_file.add_command(label='另存为…', command=lambda: self.save(save_as=True))
        ldo_file.add_command(label='导出设计报告…', command=self.export_current_report)
        ldo_file.add_separator()
        ldo_file.add_command(label='返回系统架构', command=self.back_to_architecture)
        ldo_menu.add_cascade(label='文件', menu=ldo_file)
        add_architecture_menu(ldo_menu, root)
        ldo_help = tk.Menu(ldo_menu, tearoff=False)
        add_github_menu_item(ldo_help, root)
        ldo_menu.add_cascade(label='帮助', menu=ldo_help)
        root.configure(menu=menubar)
        style = ttk.Style(root)
        if style.theme_use() != 'clam':
            style.theme_use('clam')
        style.configure('System.TFrame', background=BG)
        style.configure('System.TLabel', background=BG, foreground=INK, font=('Microsoft YaHei UI', -14))
        from ui_preferences import style_conclusion
        style_conclusion(style, 14)
        style_conclusion(style, 14, 'SystemConclusion.TLabel')
        for name, padding in [('System.TButton', (12, 7)), ('SystemToolbar.TButton', (12, 8)),
                              ('SystemMini.TButton', (8, 4))]:
            style.configure(name, padding=padding, font=('Microsoft YaHei UI', -13),
                            background='white', foreground=INK, bordercolor='#cedbea',
                            lightcolor='white', darkcolor='white', relief='flat')
            style.map(name, background=[('active', '#e7f0ff')],
                      bordercolor=[('focus', BLUE), ('active', '#9bbdeb')])
        style.configure('SystemPrimary.TButton', padding=(12, 8), font=('Microsoft YaHei UI', -13, 'bold'),
                        background=BLUE, foreground='white', bordercolor=BLUE,
                        lightcolor=BLUE, darkcolor=BLUE, relief='flat')
        style.map('SystemPrimary.TButton', background=[('disabled', '#e6eef8'), ('active', '#0c53b5')],
                  foreground=[('disabled', MUTED)], bordercolor=[('disabled', '#e6eef8'), ('focus', '#82b7fc')])
        style.configure('SystemCard.TFrame',background='white')
        style.configure('System.TEntry',padding=7,fieldbackground='white',bordercolor='#d8e3ef',font=('Microsoft YaHei UI',-14))
        style.configure('System.TCheckbutton',background='white',foreground=INK,font=('Microsoft YaHei UI',-13))
        style.configure('System.TCombobox',padding=7,fieldbackground='white',bordercolor='#d8e3ef')
        self._build_workbench_header()
        self._views = ttk.Frame(root, style='System.TFrame')
        self._views.pack(fill='both', expand=True)
        self._views.columnconfigure(0, weight=1)
        self._views.rowconfigure(0, weight=1)
        self._architecture = ttk.Frame(self._views, style='System.TFrame')
        self._architecture.grid(row=0, column=0, sticky='nsew')
        self._opening_view = ttk.Frame(self._views, style='System.TFrame', padding=24)
        ttk.Label(self._opening_view, text='正在打开电源设计…', style='System.TLabel').place(relx=.5, rely=.43, anchor='center')
        bar = ttk.Frame(self._architecture, style='System.TFrame', padding=(20, 12, 20, 6))
        bar.pack(fill='x')
        filebar = ttk.Frame(bar, style='System.TFrame')
        filebar.grid(row=0, column=0, sticky='w')
        for i, (text, command) in enumerate([('新建工程', self.new), ('打开工程或导入配置…', self.open_file),
                                             ('查看系统检查', self.show_checks)]):
            ttk.Button(filebar, text=text, command=command, style='SystemToolbar.TButton').grid(
                row=0, column=i, sticky='ew', padx=(0, 8))
        self.metrics = tk.StringVar()
        self.check_summary = tk.StringVar(value='正在检查供电预算与接口…')
        utilities = ttk.Frame(bar, style='System.TFrame')
        utilities.grid(row=0, column=1, sticky='e')
        self.title = tk.StringVar(value=self.project['title'])
        ttk.Label(utilities, text='工程名称', style='System.TLabel').pack(side='left', padx=(0, 8))
        entry = ttk.Entry(utilities, textvariable=self.title, width=23, style='System.TEntry',
                          font=('Microsoft YaHei UI', -14))
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<FocusOut>', lambda e: self.rename_project())
        entry.bind('<Return>', lambda e: self.rename_project())
        self._projectbar=bar;self._project_filebar=filebar;self._project_utilities=utilities;self._project_toolbar_rows=None
        bar.columnconfigure(0,weight=1);bar.bind('<Configure>',self.layout_project_toolbar)
        nodebar = ttk.Frame(self._architecture, style='System.TFrame', padding=(20, 0, 20, 10))
        nodebar.pack(fill='x')
        self._nodebar=nodebar;self._node_buttons=[];self._node_columns=0
        for text, command in [('增加输入源', self.add_bus), ('增加电源模块', self.add_unit),
                              ('增加 LDO',self.add_ldo),
                              ('增加 OR 汇流', lambda:self.add_node('junction')), ('增加负载', lambda:self.add_node('load')),
                              ('自动排列', self.arrange), ('撤销删除', self.undo)]:
            self._node_buttons.append(ttk.Button(nodebar, text=text, command=command, style='SystemToolbar.TButton'))
        nodebar.bind('<Configure>',self.layout_node_toolbar)
        self.layout_node_toolbar()
        split = ttk.Panedwindow(self._architecture, orient='horizontal')
        split.pack(fill='both', expand=True, padx=22)
        board = ttk.Frame(split,style='SystemCard.TFrame')
        split.add(board, weight=4)
        tools = tk.Frame(board, bg='white', padx=14, pady=10)
        tools.grid(row=0, column=0, columnspan=2, sticky='ew')
        board_title = tk.Frame(tools, bg='white')
        board_title.pack(side='left', fill='x', expand=True)
        tk.Label(board_title, text='供电网络', bg='white', fg=INK, font=('Microsoft YaHei UI', -16, 'bold'),
                 anchor='w').pack(fill='x')
        conclusion = tk.Label(board_title, textvariable=self.check_summary, bg='white', fg=INK,
                              font=('Microsoft YaHei UI', -14, 'bold'), anchor='w', justify='left')
        conclusion.pack(fill='x', pady=(2, 1))
        board_title.bind('<Configure>', lambda event: conclusion.configure(wraplength=max(120, event.width)))
        tk.Label(board_title, textvariable=self.metrics, bg='white', fg=MUTED, font=('Microsoft YaHei UI', -12),
                 anchor='w').pack(fill='x')
        for text,command in [('适应画布',self.fit_canvas),('＋',lambda:self.set_zoom(self.zoom*1.2)),('－',lambda:self.set_zoom(self.zoom/1.2))]:
            ttk.Button(tools,text=text,command=command,style='SystemMini.TButton').pack(side='right',padx=3)
        self.zoom_text=tk.StringVar(value='100%')
        tk.Label(tools,textvariable=self.zoom_text,bg='white',fg=MUTED,font=('Segoe UI',-13)).pack(side='right',padx=10)
        self.canvas = tk.Canvas(board, bg='#f9fbfe', highlightthickness=1, highlightbackground='#dce5ef')
        sx = ttk.Scrollbar(board, orient='horizontal', command=self.canvas.xview)
        sy = ttk.Scrollbar(board, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.grid(row=1, column=0, sticky='nsew')
        sy.grid(row=1, column=1, sticky='ns')
        sx.grid(row=2, column=0, sticky='ew')
        board.rowconfigure(1, weight=1)
        board.columnconfigure(0, weight=1)
        side = ttk.Frame(split, width=340,style='SystemCard.TFrame')
        split.add(side, weight=1)
        tk.Label(side,text='节点与支路',bg='white',fg=INK,font=('Microsoft YaHei UI',-16,'bold'),anchor='w',padx=16,pady=12).pack(fill='x')
        ttk.Separator(side).pack(fill='x')
        footer=ttk.Frame(side,style='SystemCard.TFrame',padding=12);footer.pack(side='bottom',fill='x')
        self.edit_state=tk.StringVar(value='请先选择节点或支路')
        self.inspector_save=ttk.Button(footer,text='保存节点修改',style='SystemPrimary.TButton',command=self.save_inspector,state='disabled')
        edit_hint = ttk.Label(footer, textvariable=self.edit_state, font=('Microsoft YaHei UI', -12),
                              background='white', foreground=MUTED)
        edit_hint.pack(fill='x', pady=(0, 8))
        self.inspector_save.pack(fill='x')
        footer.bind('<Configure>', lambda event: edit_hint.configure(wraplength=max(100, event.width-24)))
        scroll = tk.Canvas(side, highlightthickness=0, bg='white', width=320)
        self.inspector_scroll=scroll
        vs = ttk.Scrollbar(side, orient='vertical', command=scroll.yview)
        scroll.configure(yscrollcommand=vs.set)
        vs.pack(side='right', fill='y')
        scroll.pack(side='left', fill='both', expand=True)
        self.inspector = ttk.Frame(scroll, padding=(16, 12), style='SystemCard.TFrame')
        inner = scroll.create_window((0, 0), window=self.inspector, anchor='nw')
        self.inspector.bind('<Configure>', lambda e: scroll.configure(scrollregion=scroll.bbox('all')))
        def resize_inspector(event):
            scroll.itemconfigure(inner, width=event.width)
            for child in self.inspector.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=max(120, event.width-32))
        scroll.bind('<Configure>', resize_inspector)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Double-1>', self.double)
        self.canvas.bind('<Delete>', lambda e: self.delete_selected())
        self.canvas.bind('<Escape>', lambda e: self.cancel_link())
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<ButtonPress-2>',self.pan_start)
        self.canvas.bind('<B2-Motion>',self.pan_motion)
        self.canvas.bind('<ButtonRelease-2>',self.end_pan)
        self.canvas.bind('<Motion>',self.hover)
        self.status = tk.StringVar(value='正在准备架构…')
        activity = ttk.Label(self._architecture, textvariable=self.status, style='System.TLabel', padding=(24, 9))
        activity.pack(fill='x')
        activity.bind('<Configure>', lambda event: activity.configure(wraplength=max(200, event.width - 48)))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Control-Return>', lambda _event: self.save_inspector() if not self.calculator else None)
        root.bind('<Control-s>', lambda _event: self.save())
        root.bind('<Control-o>', lambda _event: self.open_current_config())
        root.bind('<Control-e>', lambda _event: self.export_current_report())
        root.bind('<Destroy>',self.cancel_toolbar_layout,add='+')
        root.after(30, self.initialize)

    def _build_workbench_header(self):
        from ui_preferences import font_control, font_size

        style = ttk.Style(self.root)
        style.configure('Workbench.TFrame', background=INK)
        style.configure('WorkbenchTitle.TLabel', background=INK, foreground='white')
        style.configure('WorkbenchMeta.TLabel', background=INK, foreground='#b5c8df')
        style.configure('Workbench.TButton', background='#203952', foreground='white',
                        bordercolor='#35536f', lightcolor='#203952', darkcolor='#203952', padding=(10, 6))
        style.map('Workbench.TButton', background=[('active', '#2d4d6d')])
        style.configure('WorkbenchLink.TButton', background=INK, foreground='#b5d5f8',
                        bordercolor=INK, lightcolor=INK, darkcolor=INK, padding=(9, 6))
        style.map('WorkbenchLink.TButton', background=[('active', '#203952')], foreground=[('active', 'white')])
        for name in ('WorkbenchPrimary.TButton', 'Workbench.TMenubutton'):
            style.configure(name, background=BLUE, foreground='white', bordercolor=BLUE,
                            lightcolor=BLUE, darkcolor=BLUE, padding=(11, 6))
            style.map(name, background=[('active', '#0e58b7')])

        head = self._header = ttk.Frame(self.root, style='Workbench.TFrame', padding=(18, 10))
        head.pack(fill='x')
        head.columnconfigure(0, weight=1)
        location = self._header_location = ttk.Frame(head, style='Workbench.TFrame')
        location.grid(row=0, column=0, sticky='ew')
        self._back_button = ttk.Button(location, text='← 系统架构', style='Workbench.TButton',
                                       command=self.back_to_architecture)
        labels = ttk.Frame(location, style='Workbench.TFrame')
        labels.pack(side='left', fill='x', expand=True)
        self._context_title = tk.StringVar(value='系统架构')
        self._save_state = tk.StringVar(value='开关电源设计工作台')
        self._header_title = ttk.Label(labels, textvariable=self._context_title, style='WorkbenchTitle.TLabel')
        self._header_title.pack(anchor='w', fill='x')
        self._header_status = ttk.Label(labels, textvariable=self._save_state, style='WorkbenchMeta.TLabel')
        self._header_status.pack(anchor='w', fill='x', pady=(2, 0))

        actions = self._header_actions = ttk.Frame(head, style='Workbench.TFrame')
        actions.grid(row=0, column=1, sticky='e')
        self._header_stacked = False
        self.report_button = ttk.Button(actions, text='导出系统报告', command=self.export_report,
                                        style='WorkbenchPrimary.TButton')
        self.report_button.grid(row=0, column=4, sticky='ew')
        self._unit_report_button = ttk.Menubutton(actions, text='导出报告', style='Workbench.TMenubutton')
        self._simulation_button = ttk.Button(actions, text='仿真配置', style='Workbench.TButton',
                                             command=self.open_current_simulation)
        self._simulation_button.grid(row=0, column=3, padx=(0, 8), sticky='ew')
        self._calculate_button = ttk.Button(actions, text='重新计算', style='Workbench.TButton',
                                            command=self.calculate_current)
        ttk.Button(actions, text='保存工程', style='Workbench.TButton', command=self.save).grid(
            row=0, column=1, padx=(0, 8), sticky='ew')
        font_slot = ttk.Frame(actions, style='Workbench.TFrame')
        font_slot.grid(row=0, column=0)
        self._font_choice = font_control(font_slot, self.choose_font, style='Workbench')
        self._github_button = ttk.Button(actions, text=GITHUB_LABEL, style='WorkbenchLink.TButton',
                                         command=lambda: open_github(self.root))
        self._github_button.grid(row=0, column=5, padx=(8, 0), sticky='ew')
        self._style_workbench_font(font_size())
        head.bind('<Configure>', self._layout_workbench_header)
        location.bind('<Configure>', self._wrap_workbench_location)

    def _style_workbench_font(self, value):
        style = ttk.Style(self.root)
        size = min(value, 22)
        family = 'Microsoft YaHei UI'
        style.configure('WorkbenchTitle.TLabel', font=(family, -min(value + 5, 28), 'bold'))
        style.configure('WorkbenchMeta.TLabel', font=(family, -size))
        for name in ('Workbench.TButton', 'WorkbenchPrimary.TButton', 'Workbench.TMenubutton'):
            style.configure(name, font=(family, -size, 'bold'))
        style.configure('WorkbenchLink.TButton', font=(family, -min(size, 17)))

    def _wrap_workbench_location(self, event):
        back_width = self._back_button.winfo_reqwidth() + 12 if self._back_button.winfo_manager() else 0
        wrap = max(130, event.width - back_width - 12)
        self._header_title.configure(wraplength=wrap)
        self._header_status.configure(wraplength=wrap)

    def _layout_workbench_header(self, _event=None):
        stacked = self._header_actions.winfo_reqwidth() + 400 > self._header.winfo_width()
        if stacked == self._header_stacked:
            return
        self._header_stacked = stacked
        self._header_location.grid_configure(columnspan=2 if stacked else 1)
        self._header_actions.grid_configure(row=int(stacked), column=0 if stacked else 1,
                                            columnspan=2 if stacked else 1, pady=(7, 0) if stacked else 0)

    def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        restored = False
        try:
            if self.use_recovery and model.recovery_path().is_file():
                self.project = model.load_project(model.recovery_path())
                restored = True
                self.status.set('已恢复上次工程。点击「保存工程」可保存为 JSON 文件。')
            else:
                self.project = model.normalize_project(self.project)
                self.status.set('双击电源模块可进入设计计算。')
        except Exception as error:
            self.project = model.normalize_project(model.fresh_project())
            self.status.set('恢复工程失败，已打开默认架构。' + str(error))
        self.title.set(self.project['title'])
        self.render()
        from ui_preferences import apply_studio_fonts
        apply_studio_fonts(self._architecture, int(self._font_choice.get()))
        if not restored:
            self._project_baseline = copy.deepcopy(self.project)
        self.root.after_idle(self.fit_canvas)

    def changed(self, note='架构已更新。点击「保存工程」写入文件。'):
        self._refresh_save_state()
        if self.use_recovery:
            try:
                model.save_project(self.project, model.recovery_path())
            except Exception as error:
                self.status.set('自动恢复文件写入失败。请保存工程。' + str(error))
                return
        self.status.set(note)

    def _refresh_save_state(self):
        if self._opening_unit is not None:
            return
        if self.project != self._project_baseline:
            self._save_state.set('工程有未保存修改')
        else:
            self._save_state.set('已保存到工程文件' if self.path else '系统工程')

    def rename_project(self):
        title = self.title.get().strip()[:120]
        if title and title != self.project['title']:
            self.project['title'] = title
            self.changed()

    def render(self):
        self._review=None
        positions = self.project.setdefault('layout', {}).setdefault('nodes', {})
        if not positions:
            model.auto_layout(self.project)
            positions = self.project['layout']['nodes']
        self.nodes = {}
        for kind, collection in model.COLLECTIONS.items():
            for i, item in enumerate(self.project[collection]):
                key = kind + ':' + item['id']
                if key not in positions:
                    point=dict(x={'bus':40,'unit':425,'junction':810,'load':1195}[kind],y=50+i*240)
                    while any(abs(p['x']-point['x'])<320 and abs(p['y']-point['y'])<210 for p in positions.values()):
                        point['y']+=240
                    positions[key]=point
                self.nodes[key] = (kind, item, positions[key])
        self.metrics.set(f"{len(self.project['sources'])} 个输入源 · {len(self.project['units'])} 个模块 · "
                         f"{len(self.project['loads'])} 个负载 · {len(self.project['connections'])} 条供电支路")
        try:
            self._review = model.checks(self.project)
            self.check_summary.set(self._check_status(self._review))
        except Exception as error:
            self.check_summary.set('系统检查未完成。' + str(error))
        self.draw()
        self.show_inspector()

    def draw(self):
        from system_canvas import draw_network
        draw_network(self)

    def choose_font(self,value):
        from ui_preferences import apply_studio_fonts, save_font_size
        value = save_font_size(value)
        self._font_choice.set(str(value))
        self._style_workbench_font(value)
        apply_studio_fonts(self._architecture, value)
        self._layout_workbench_header()
        if self.calculator is not None:
            self.calculator.set_font_size(value)
            self._editor['font_size'] = value
        if self._toolbar_layout_job:self.root.after_cancel(self._toolbar_layout_job)
        def layout():
            self._toolbar_layout_job=None
            self.layout_node_toolbar();self.layout_project_toolbar()
        self._toolbar_layout_job=self.root.after_idle(layout)
        self.status.set(f'界面字号已设为 {value} px。图内文字随画布缩放。')

    def layout_node_toolbar(self,event=None):
        minimum=max(140,max(b.winfo_reqwidth() for b in self._node_buttons))
        columns=next((n for n in (len(self._node_buttons),4,3,2) if self._nodebar.winfo_width()>=n*(minimum+8)+40),1)
        if columns==self._node_columns:return
        self._node_columns=columns
        for column in range(len(self._node_buttons)):self._nodebar.columnconfigure(column,weight=1 if column<columns else 0,minsize=0,uniform='node-actions' if column<columns else '')
        for i,button in enumerate(self._node_buttons):button.grid(row=i//columns,column=i%columns,sticky='ew',padx=(0,8) if i%columns<columns-1 else 0,pady=4)

    def layout_project_toolbar(self,event=None):
        width=self._projectbar.winfo_width()
        if width<100:return
        split=self._project_filebar.winfo_reqwidth()+self._project_utilities.winfo_reqwidth()+40>width
        if split==self._project_toolbar_rows:return
        self._project_toolbar_rows=split
        self._project_filebar.grid(columnspan=2 if split else 1,sticky='ew' if split else 'w')
        self._project_utilities.grid(row=1 if split else 0,column=0 if split else 1,columnspan=2 if split else 1,
                                     sticky='ew' if split else 'e',pady=(8,0) if split else 0)

    def cancel_toolbar_layout(self,event):
        if event.widget is self.root and self._toolbar_layout_job:
            self.root.after_cancel(self._toolbar_layout_job);self._toolbar_layout_job=None

    def mark_edit_dirty(self,*_):
        self._edit_dirty=True
        self.inspector_save.configure(state='normal')
        self.edit_state.set('有未应用修改。按 Ctrl+Enter 可应用。')

    def save_inspector(self):
        if not self._edit_dirty or self._commit_edit is None:return True
        return self._commit_edit() is not False

    def request_draw(self):
        if self._draw_job is None:
            self._draw_job=self.root.after(16,self.flush_draw)

    def flush_draw(self):
        if self._draw_job is not None:
            try:self.root.after_cancel(self._draw_job)
            except tk.TclError:pass
        self._draw_job=None
        if self._drag_dirty and self.drag:
            from system_canvas import update_drag
            update_drag(self,self.drag['key'],self.drag['kind']);self._drag_dirty=False
        else:self.draw()

    def world_point(self,e):
        return self.canvas.canvasx(e.x)/self.zoom,self.canvas.canvasy(e.y)/self.zoom

    def set_zoom(self,value,anchor=None):
        x,y=anchor or (self.canvas.winfo_width()/2,self.canvas.winfo_height()/2)
        wx,wy=self.canvas.canvasx(x)/self.zoom,self.canvas.canvasy(y)/self.zoom
        self.zoom=max(.35,min(2.2,value));self.zoom_text.set(f'{self.zoom:.0%}')
        self.draw()
        region=self.canvas.bbox('all')
        scroll=self.canvas.cget('scrollregion').split()
        if region and len(scroll)==4:
            self.canvas.xview_moveto(max(0,(wx*self.zoom-x)/float(scroll[2])))
            self.canvas.yview_moveto(max(0,(wy*self.zoom-y)/float(scroll[3])))
        self.draw()

    def fit_canvas(self):
        if not self.initialized:return
        self.canvas.update_idletasks()
        left,top,right,bottom=scene_bounds(self.project)
        z=min((self.canvas.winfo_width()-60)/max(1,right-left+70),(self.canvas.winfo_height()-60)/max(1,bottom-top+70),1.25)
        self.zoom=max(.35,z);self.zoom_text.set(f'{self.zoom:.0%}');self.draw()
        scroll=self.canvas.cget('scrollregion').split()
        self.canvas.xview_moveto(max(0,(left-35)*self.zoom/float(scroll[2])))
        self.canvas.yview_moveto(max(0,(top-35)*self.zoom/float(scroll[3])))
        self.draw()

    def wheel(self,e):
        if e.state & 4:self.set_zoom(self.zoom*(1.12 if e.delta>0 else 1/1.12),(e.x,e.y))
        else:
            (self.canvas.xview_scroll if e.state&1 else self.canvas.yview_scroll)(-int(e.delta/120),'units')
            self.request_draw()
        return 'break'

    def pan_start(self,e):
        self._panning=True;self.canvas.scan_mark(e.x,e.y)

    def pan_motion(self,e):
        if self._panning:self.canvas.scan_dragto(e.x,e.y,gain=1)

    def end_pan(self,e=None):
        self._panning=False;self.draw()

    def hover(self,e):
        if self.drag or self._panning:return
        hit=self.hit(e)
        kind=hit[0] if hit else ''
        self.canvas.configure(cursor='crosshair' if kind in ('input','output') else 'hand2' if kind in ('open','delete') else 'fleur' if kind in (*model.COLLECTIONS,'diode') else 'arrow')

    def hit(self, e):
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        items = self.canvas.find_overlapping(x - 5, y - 5, x + 5, y + 5)
        return next((self.hits[i] for i in reversed(items) if i in self.hits), None)

    def press(self, e):
        self.canvas.focus_set()
        self.drag=None
        hit = self.hit(e)
        if self._edit_dirty:
            if not self.save_inspector():return
        if not hit:
            self.selected = None
            self.pan_start(e)
            self.draw();self.show_inspector()
            return
        kind, identity = hit
        if kind == 'delete':
            self.selected = tuple(identity.split(':', 1))
            self.delete_selected()
        elif kind == 'open':
            self.schedule_open_unit(identity)
        elif kind == 'output':
            self.link = identity
            self.status.set('点击或拖到目标模块的 IN 端口；Esc 取消连线。')
        elif kind == 'input':
            if self.link:
                self.finish_link(identity)
        elif kind=='diode':
            self.selected=('edge',identity)
            edge=next(v for v in self.project['connections'] if v['id']==identity)
            p=diode_point(self.project,edge);x,y=self.world_point(e)
            self.drag=dict(key=identity,kind='diode',x=x,y=y,original=p,moved=False)
            self.draw();self.show_inspector()
        else:
            self.selected = hit
            if kind in model.COLLECTIONS:
                p = self.project['layout']['nodes'][kind + ':' + identity]
                x,y=self.world_point(e)
                self.drag = dict(key=kind + ':' + identity,kind='node', x=x,y=y, original=dict(p), moved=False)
            self.draw()
            self.show_inspector()

    def motion(self, e):
        x, y = self.world_point(e)
        if self.drag:
            d = self.drag
            p = self.project['layout'].setdefault('diodes',{}).setdefault(d['key'],dict(d['original'])) if d['kind']=='diode' else self.project['layout']['nodes'][d['key']]
            p.update(x=max(48 if d['kind']=='diode' else 24, min(10000, d['original']['x'] + x - d['x'])), y=max(32 if d['kind']=='diode' else 24, min(10000, d['original']['y'] + y - d['y'])))
            d['moved'] = True
            self._drag_dirty=True
            self.request_draw()
        elif self.link:
            self.canvas.delete('pending')
            source = self.nodes[self.link['kind'] + ':' + self.link['id']][2]
            yy = source['y'] + (102 if self.link['kind'] == 'bus' else 119 + 26 * (self.link['output'] - 1))
            self.canvas.create_line((source['x']+288)*self.zoom, yy*self.zoom, x*self.zoom, y*self.zoom, width=2, dash=(6, 3), fill=BLUE, tags='pending')
        elif self._panning:self.pan_motion(e)

    def release(self, e):
        was_panning=self._panning
        if self.drag and self.drag['moved']:
            self.flush_draw()
            self.draw() # Update viewport bounds once, after the gesture.
            self.changed('二极管位置已保存，连线随位置更新。' if self.drag['kind']=='diode' else '节点位置已保存。拖动不触发电源计算。')
        self.drag = None
        self._panning=False
        if was_panning:self.draw()
        hit = self.hit(e)
        if self.link and hit and hit[0] == 'input':
            self.finish_link(hit[1])

    def double(self, e):
        hit = self.hit(e)
        if hit and hit[0] == 'unit':
            self.drag = None
            self.schedule_open_unit(hit[1])
        else:
            # Tk replaces the single-press binding on the second click. Keep
            # non-calculator objects draggable even after a rapid double-click.
            self.press(e)

    def finish_link(self, target):
        try:
            model.connect(self.project, target, self.link)
            self.changed('已新增供电关系，原连接保留。多源接入已按二极管 OR 配置；点连线编辑 Vf。')
        except Exception as error:
            self.status.set(str(error))
        self.link = None
        self.render()

    def cancel_link(self):
        self.link = None
        self.canvas.delete('pending')
        self.status.set('连线已取消。')

    def show_inspector(self):
        self._edit_dirty=False;self._commit_edit=None;self._inspector_vars=[]
        self.inspector_save.configure(state='disabled',text='保存支路修改' if self.selected and self.selected[0]=='edge' else '保存节点修改')
        self.edit_state.set('当前设置已应用。保存工程后将写入文件。' if self.selected else '请先选择节点或支路')
        for w in self.inspector.winfo_children():
            w.destroy()
        def label(text, *, heading=False):
            tk.Label(self.inspector, text=text, bg='white', fg=INK if heading else MUTED,
                     wraplength=max(120, self.inspector_scroll.winfo_width()-32), justify='left',
                     anchor='w', font=('Microsoft YaHei UI', -15 if heading else -13, 'bold' if heading else 'normal')).pack(
                         fill='x', pady=(0, 10))

        def make_form():
            form = ttk.Frame(self.inspector, style='SystemCard.TFrame')
            form.columnconfigure(0, weight=2, uniform='field')
            form.columnconfigure(1, weight=3, uniform='field')
            form.pack(fill='x', pady=(0, 6))
            labels = []
            def resize(event):
                for item in labels:
                    item.configure(wraplength=max(64, int((event.width-30)*.37)))
            form.bind('<Configure>', resize)
            return form, labels

        def field(form, labels, row, text, variable, unit='', *, choices=None):
            title = tk.Label(form, text=text, bg='white', fg=INK, justify='left', anchor='w',
                             wraplength=108, font=('Microsoft YaHei UI', -13))
            title.grid(row=row, column=0, sticky='ew', padx=(0, 8), pady=4)
            labels.append(title)
            if choices:
                control = ttk.Combobox(form, textvariable=variable, values=choices, state='readonly',
                                       width=8, style='System.TCombobox', font=('Microsoft YaHei UI', -14))
            else:
                control = ttk.Entry(form, textvariable=variable, width=8, style='System.TEntry',
                                    font=('Microsoft YaHei UI', -14))
            control.grid(row=row, column=1, columnspan=1 if unit else 2, sticky='ew', pady=4)
            if unit:
                tk.Label(form, text=unit, bg='white', fg=MUTED, font=('Segoe UI', -13)).grid(
                    row=row, column=2, sticky='w', padx=(8, 0))

        self.inspector_scroll.yview_moveto(0)
        if not self.selected:
            label('选择节点或支路', heading=True)
            label('拖动卡片调整位置，从输出端口拖到输入端口建立供电关系。')
            label('双击电源模块进入设计。')
        if self.selected:
            kind, identity = self.selected
            if kind == 'edge':
                edge = next(e for e in self.project['connections'] if e['id']==identity)
                label(identity + ' · 供电支路', heading=True)
                label(f"{edge['source']['id']} / OUT{edge['source']['output']} → {edge['target']}")
                mode=tk.StringVar(value='二极管隔离 / OR' if edge['mode']=='diode' else '直连')
                vf=tk.StringVar(value=str(edge['vf']))
                enabled=tk.BooleanVar(value=edge['enabled'])
                form, labels = make_form()
                field(form, labels, 0, '支路类型', mode, choices=['直连', '二极管隔离 / OR'])
                field(form, labels, 1, '二极管压降 Vf', vf, 'V')
                ttk.Checkbutton(self.inspector,text='启用此供电支路',variable=enabled).pack(anchor='w',pady=8)
                def apply_edge():
                    try:
                        candidate=copy.deepcopy(self.project)
                        item=next(e for e in candidate['connections'] if e['id']==identity)
                        item.update(mode='diode' if mode.get()!='直连' else 'direct',vf=float(vf.get()),enabled=enabled.get())
                        self.project=model.normalize_project(candidate)
                        self.changed('支路设置已更新。')
                        self.render()
                        return True
                    except Exception as error:
                        messagebox.showerror('供电支路',str(error),parent=self.root)
                        return False
                self._commit_edit=apply_edge;self._inspector_vars=[mode,vf,enabled]
                if edge['mode']=='diode':
                    def reset_diode():
                        self.project['layout'].setdefault('diodes',{}).pop(identity,None)
                        self.changed('二极管已恢复自动布置。');self.render()
                    ttk.Button(self.inspector,text='重置二极管位置',command=reset_diode).pack(fill='x',pady=6)
                ttk.Button(self.inspector, text='断开连接', command=lambda: self.disconnect(identity)).pack(fill='x')
            else:
                item = next((n for n in self.project[model.COLLECTIONS[kind]] if n['id'] == identity), None)
                if item:
                    label(identity + ' · 节点配置', heading=True)
                    fields = [('name', '名称', '')]
                    if kind == 'bus':
                        fields += [('min', '最小电压', 'V'), ('max', '最大电压', 'V'), ('capacity', '输入容量', 'W')]
                    if kind=='load':
                        fields += [('power', '负载功耗', 'W'), ('min', '允许输入下限', 'V'), ('max', '允许输入上限', 'V')]
                    elif kind=='junction':
                        fields += [('capacity', 'OR 母线容量', 'W')]
                    variables = {}
                    form, labels = make_form()
                    for row, (key, text, unit) in enumerate(fields):
                        v = tk.StringVar(value=str(item[key]))
                        field(form, labels, row, text, v, unit)
                        variables[key] = v
                    if kind == 'load':
                        label('输入上下限为 0 时，表示该项不限。')
                    enabled=tk.BooleanVar(value=item['enabled'])
                    ttk.Checkbutton(self.inspector,text='启用节点（取消可模拟掉电）',variable=enabled).pack(anchor='w',pady=8)
                    def apply():
                        try:
                            candidate = copy.deepcopy(self.project)
                            obj = next(n for n in candidate[model.COLLECTIONS[kind]] if n['id'] == identity)
                            obj.update({k: v.get() if k == 'name' else float(v.get()) for k, v in variables.items()})
                            obj['enabled']=enabled.get()
                            self.project = model.normalize_project(candidate)
                            self.changed()
                            self.render()
                            return True
                        except Exception as error:
                            messagebox.showerror('节点配置', str(error), parent=self.root)
                            return False
                    self._commit_edit=apply;self._inspector_vars=[*variables.values(),enabled]
                    if kind != 'bus':
                        label('新增供电关系（保留现有支路）')
                        values, sources = ['选择上游输出…'], [None]
                        for bus in self.project['sources']:
                            values.append(bus['id'] + ' · DC')
                            sources.append(dict(kind='bus', id=bus['id'], output=1))
                        for unit in self.project['units']:
                            if unit['id'] == identity:
                                continue
                            for i, rail in enumerate(unit['rails'], 1):
                                values.append(f"{unit['id']} · OUT{i} · {rail['V_out']:.4g} V")
                                sources.append(dict(kind='unit', id=unit['id'], output=i))
                        for junction in self.project['junctions']:
                            if junction['id']!=identity:
                                values.append(junction['id']+' · OR 母线')
                                sources.append(dict(kind='junction',id=junction['id'],output=1))
                        box = ttk.Combobox(self.inspector, values=values, state='readonly', width=27)
                        box.current(0)
                        box.pack(fill='x', pady=(0, 10))
                        box.bind('<<ComboboxSelected>>', lambda e: self.choose_source(identity, sources[box.current()]) if box.current()>0 else None)
                        for edge in model.incoming(self.project,identity):
                            text=f"{edge['source']['id']} · "+(f"Vf {edge['vf']:g} V" if edge['mode']=='diode' else '直连')+(' · 已停用' if not edge['enabled'] else '')
                            def edit_branch(eid=edge['id']):
                                self.selected=('edge',eid)
                                self.render()
                            ttk.Button(self.inspector,text=text+' · 编辑',command=edit_branch).pack(fill='x',pady=4)
                    if kind == 'unit':
                        ttk.Button(self.inspector, text='沿用上游电压', command=lambda: self.sync(identity)).pack(fill='x', pady=6)
                        ttk.Button(self.inspector, text='进入电源设计 →', style='SystemPrimary.TButton',
                                   command=lambda: self.schedule_open_unit(identity)).pack(fill='x', pady=6)
                    ttk.Button(self.inspector, text='删除节点', command=self.delete_selected).pack(fill='x', pady=6)
        for widget in self.inspector.winfo_children():
            if isinstance(widget,ttk.Button) and not widget.cget('style'):widget.configure(style='System.TButton')
            elif isinstance(widget,ttk.Combobox):widget.configure(style='System.TCombobox',font=('Microsoft YaHei UI',-14))
            elif isinstance(widget,ttk.Entry):widget.configure(style='System.TEntry',font=('Microsoft YaHei UI',-14))
            elif isinstance(widget,ttk.Checkbutton):widget.configure(style='System.TCheckbutton')
        for variable in self._inspector_vars:variable.trace_add('write',self.mark_edit_dirty)
        from ui_preferences import apply_studio_fonts,font_size
        apply_studio_fonts(self.inspector, font_size())

    @staticmethod
    def _check_status(check):
        if not (check['capacity'] or check['interfaces']):
            return '暂无可检查的供电端口或节点'
        capacity = sum(not row['ok'] for row in check['capacity'])
        interfaces = sum(not row['ok'] or bool(row['unavailable']) for row in check['interfaces'])
        if capacity or interfaces:
            return f'待复核 · 功率预算 {capacity} 项 · 电压与失电 {interfaces} 项'
        return '已算稳态预算与电源接口满足当前配置'

    def show_checks(self):
        try:check=model.checks(self.project)
        except Exception as error:
            messagebox.showerror('系统检查',str(error),parent=self.root);return
        window=tk.Toplevel(self.root);window.title('系统供电预算与接口检查');window.geometry('1000x620')
        ttk.Label(window, text=self._check_status(check), style='SystemConclusion.TLabel').pack(
            fill='x', padx=16, pady=(16, 5))
        book=ttk.Notebook(window);book.pack(fill='both',expand=True,padx=16,pady=(0, 8))
        def page(title,headers,rows):
            frame=ttk.Frame(book);book.add(frame,text=title)
            tree=ttk.Treeview(frame,columns=tuple(range(len(headers))),show='headings',selectmode='browse')
            vs=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=vs.set)
            tree.pack(side='left',fill='both',expand=True);vs.pack(side='right',fill='y')
            for i,h in enumerate(headers):tree.heading(i,text=h);tree.column(i,width=145,anchor='w')
            tree.tag_configure('warn',background='#fff4e5',foreground='#976122')
            for values,ok in rows:tree.insert('', 'end', values=values,tags=() if ok else ('warn',))
        page('功率预算',['端口','正常功率 / W','已算最大功率 / W','配置容量 / W','状态'],[
            ((r['port'],f"{r['normal']:.4g}",f"{r['allocated']:.4g}",f"{r['capacity']:.4g}",'满足容量' if r['ok'] else '待复核'),r['ok']) for r in check['capacity']])
        page('电压与失电',['节点','可用电压 / V','允许范围 / V','状态'],[
            ((r['name'],'无供电' if r['source_min'] is None else f"{r['source_min']:.4g}–{r['source_max']:.4g}",f"{r['design_min']:.4g}–{r['design_max']:.4g}",r['note']),r['ok'] and not r['unavailable']) for r in check['interfaces']])
        ttk.Label(window,text='预算按固定二极管压降计算。OR 支路优先使用高压源，同压时分别检查供电容量。',
                  style='System.TLabel', padding=(16, 8)).pack(fill='x')

    def choose_source(self, identity, source):
        self.link = source
        self.finish_link(identity)

    def disconnect(self, identity):
        model.disconnect(self.project, identity)
        self.selected=None
        self.changed('供电连接已断开，单元设计参数已保留。')
        self.render()

    def sync(self, identity):
        try:
            lo, hi = model.sync_input(self.project, identity)
            self.changed(f'输入范围已更新为 {lo:g}–{hi:g} V。')
            self.render()
        except Exception as error:
            messagebox.showerror('更新输入电压', str(error), parent=self.root)

    def add_bus(self):
        self.add_node('bus')

    def add_unit(self):
        self.add_node('unit')

    def add_ldo(self):
        if len(self.project['units'])>=24:return
        from ldo import DEFAULTS
        identity=model.next_id(self.project,'LDO')
        self.project['units'].append(dict(id=identity,name='新增 LDO 线性稳压器',spec=copy.deepcopy(DEFAULTS),enabled=True))
        self.project=model.normalize_project(self.project);self.selected=('unit',identity);self.changed('LDO 已增加，连接上游后进入专用线性稳压设计。');self.render()

    def load_ldo_example(self):
        self._load_architecture_example('SYSTEM_LDO.json')

    def add_node(self,kind):
        collection=model.COLLECTIONS[kind]
        if len(self.project[collection]) >= (24 if kind in ('bus','unit') else 48):
            return
        identity = model.next_id(self.project, {'bus':'BUS','unit':'PSU','junction':'OR','load':'LOAD'}[kind])
        item=dict(id=identity,name={'bus':'新增输入源','unit':'新增电源','junction':'二极管竞争供电母线','load':'自定义负载'}[kind],enabled=True)
        if kind=='bus':item.update(min=20,max=30,capacity=100)
        elif kind=='unit':item.update(spec=model.fresh_project()['units'][0]['spec'])
        elif kind=='junction':item.update(capacity=100)
        else:item.update(power=1,min=0,max=0)
        self.project[collection].append(item)
        self.project = model.normalize_project(self.project)
        self.selected = (kind, identity)
        self.changed()
        self.render()

    def delete_selected(self):
        if not self.selected:
            return
        kind, identity = self.selected
        if kind == 'edge':
            return self.disconnect(identity)
        self.removal = model.remove_node(self.project, kind, identity)
        self.selected = None
        self.changed('节点已删除，下级输入已断开。可撤销删除。')
        self.render()

    def undo(self):
        if self.removal:
            try:
                model.restore_node(self.project, self.removal)
                self.removal = None
                self.changed('已撤销删除。')
                self.render()
            except Exception as error:
                self.status.set(str(error))

    def arrange(self):
        model.auto_layout(self.project)
        self.changed('已按供电层级排列。')
        self.render()

    def new(self):
        self._reset_unit_views()
        self._geometry_origin=None
        self.project = model.normalize_project(model.fresh_project())
        self.title.set(self.project['title'])
        self.path, self.selected, self.removal = None, None, None
        self.changed('已创建新系统工程。上次编辑保留在手动保存的 JSON 中。')
        self.render()
        self._project_baseline = copy.deepcopy(self.project)

    def load_example(self):
        self._load_architecture_example('SYSTEM_AUX_ORING.json')

    def _load_architecture_example(self, filename):
        try:
            candidate = model.load_project(resource_path('examples/' + filename))
        except (OSError, ValueError) as error:
            messagebox.showerror('载入架构示例', str(error), parent=self.root)
            return
        if not self.save_inspector():
            return
        title = self.title.get().strip()[:120]
        if title and title != self.project['title']:
            self.rename_project()
        if self.project != self._project_baseline:
            choice = messagebox.askyesnocancel('切换架构示例', '切换前是否保存当前系统工程？', parent=self.root)
            if choice is None or (choice and not self.save()):
                return
        self._reset_unit_views()
        self._geometry_origin = None
        self.project = candidate
        self.title.set(self.project['title'])
        self.path = self.selected = self.removal = self.link = self.drag = None
        self._drag_dirty = False
        self.render()
        self._project_baseline = copy.deepcopy(self.project)
        self.changed(f"已载入架构示例 · {self.project['title']}")
        self.root.after_idle(self.fit_canvas)

    def open_file(self):
        path = filedialog.askopenfilename(parent=self.root, title='打开系统工程或原电源配置', filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            from pathlib import Path
            source=Path(path).read_bytes()
            raw=json.loads(source.decode('utf-8-sig'))
            candidate = model.load_project_data(raw)
            self._reset_unit_views()
            self.project = candidate
            self._geometry_origin=None
            if not raw.get('schema_version') and not raw.get('schema') and len(self.project['units'])==1:
                self._geometry_origin=(self.project,self.project['units'][0]['id'],(Path(path).name,source))
            self.path = path if raw.get('schema_version') == model.SCHEMA else None
            self.title.set(self.project['title'])
            self.selected, self.removal = None, None
            self.changed('已打开系统工程。' if self.path else '已将配置导入为单独的电源模块。')
            self.render()
            self._project_baseline = copy.deepcopy(self.project)
            self._save_state.set('已打开工程文件' if self.path else '已导入配置 · 待保存工程')
        except Exception as error:
            messagebox.showerror('打开工程', str(error), parent=self.root)

    def save(self, *, save_as=False):
        if self.calculator is not None and not self._apply_unit_config(self.calculator):
            return False
        if not self.save_inspector():
            return False
        self.rename_project()
        path = self.path
        if not path or save_as:
            path = filedialog.asksaveasfilename(parent=self.root, title='保存完整系统工程',
                initialfile=self.project['title'] + '.json', defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                model.save_project(self.project, path)
                self.path = path
                self._project_baseline = copy.deepcopy(self.project)
                self._save_state.set('已保存到工程文件')
                self.status.set('系统工程已保存：' + path)
                return True
            except Exception as error:
                messagebox.showerror('保存工程', str(error), parent=self.root)
        return False

    def schedule_open_unit(self, identity):
        if self._opening_unit is not None or self.calculator is not None:
            return
        if self.report_process and self.report_process.is_alive():
            self.status.set('系统报告正在生成。完成后即可进入单元设计。')
            return
        if not self.save_inspector():
            return
        project = self.project
        cached = self._editors.get(identity)
        if cached and cached['spec'] == model.unit_by_id(self.project, identity)['spec']:
            self.open_unit(identity)
            return
        self._save_state.set('正在打开电源设计…')
        self._opening_view.grid(row=0, column=0, sticky='nsew')
        self._opening_view.tkraise()

        def open_after_redraw():
            self._opening_unit = None
            try:
                if self.project is project:
                    self.open_unit(identity)
                if self.calculator is None:
                    self._save_state.set('系统工程')
            finally:
                self._opening_view.grid_remove()

        self._opening_unit = self.root.after(24, open_after_redraw)

    def open_unit(self, identity):
        if self._opening_unit is not None or self.calculator is not None:
            return None
        if self.report_process and self.report_process.is_alive():
            self.status.set('系统报告正在生成。完成后即可进入单元设计。')
            return None
        if not self.save_inspector():
            return None
        self.root.configure(cursor='watch')
        container = None
        try:
            original = model.unit_by_id(self.project, identity)
            unit = model.prepare_unit(self.project, identity)
            from ldo import is_ldo
            size = int(self._font_choice.get())
            editor = self._editors.get(identity)
            if editor and editor['spec'] == unit['spec']:
                app = editor['app']
                container = app.container
                if editor['font_size'] != size:
                    app.set_font_size(size)
                    editor['font_size'] = size
                self._editors.pop(identity)
                self._editors[identity] = editor
            else:
                self._release_editor(identity)
                if len(self._editors) >= self._MAX_EDITORS:
                    self._release_editor(next(iter(self._editors)))
                container = ttk.Frame(self._views, style='System.TFrame')
                if is_ldo(unit['spec']):
                    from ldo_ui import LdoDesigner as Designer
                else:
                    from main import PowerSupplyAnalyzer as Designer
                app = Designer(self.root, initial_config=copy.deepcopy(unit['spec']), container=container,
                               on_return=self.back_to_architecture)
                editor = {'id': identity, 'spec': copy.deepcopy(unit['spec']), 'app': app,
                          'font_size': size, 'applied_config': None}
                self._editors[identity] = editor
                if hasattr(app, 'restore_result_page'):
                    app.restore_result_page(self._unit_page_states.get(identity))
            self._editor = editor
            origin = getattr(self, '_geometry_origin', None)
            if origin and origin[0] is self.project and origin[1] == identity:
                app._geometry_source = origin[2]
            self._canvas_view = (self.canvas.xview()[0], self.canvas.yview()[0])
            self._unit_graph_changed = (unit is not original)
            self._unit_active_changed = self.project.get('activeUnit') != identity
            self.project['activeUnit'] = identity
            self._unit_detached.clear()
            self.calculator = app
            self._architecture.grid_remove()
            container.grid(row=0, column=0, sticky='nsew')
            container.tkraise()
            self._show_unit_header(unit, app)
            container.focus_set()
            return app
        except Exception as error:
            self._release_editor(identity)
            if container is not None and container.winfo_exists():
                container.destroy()
            self.calculator = None
            self._show_architecture_header()
            self._architecture.grid()
            messagebox.showerror('打开电源设计', str(error), parent=self.root)
        finally:
            self.root.configure(cursor='')

    def _show_unit_header(self, unit, app):
        self._back_button.pack(side='left', before=self._header_title.master, padx=(0, 12))
        self._context_title.set(unit['id'] + ' · ' + unit['name'])
        self._save_state.set('编辑单元参数 · 保存工程可写入文件')
        self.report_button.grid_remove()
        self._calculate_button.grid(row=0, column=2, padx=(0, 8), sticky='ew')
        menu = tk.Menu(self._unit_report_button, tearoff=False)
        if hasattr(app, '_export_report_ui'):
            menu.add_command(label='设计报告 · Word / Excel / Markdown', command=app._export_report_ui)
        else:
            for kind in ('docx', 'xlsx', 'json'):
                menu.add_command(label=kind.upper(), command=lambda fmt=kind: app.report(fmt))
        self._unit_report_button.configure(menu=menu)
        self._unit_report_button.grid(row=0, column=4, sticky='ew')
        if hasattr(app, '_open_simulation_center'):
            self._simulation_button.configure(text='仿真配置中心')
            self._simulation_button.grid()
        else:
            self._simulation_button.grid_remove()
        self.root.configure(menu=getattr(app, 'workspace_menu', self._ldo_menu))
        self._layout_workbench_header()

    def _show_architecture_header(self):
        self._back_button.pack_forget()
        self._context_title.set('系统架构')
        self._calculate_button.grid_remove()
        self._unit_report_button.grid_remove()
        menu = self._unit_report_button.cget('menu')
        if menu:
            self._unit_report_button.configure(menu='')
            self.root.nametowidget(str(menu)).destroy()
        self.report_button.grid()
        self._simulation_button.configure(text='仿真配置')
        self._simulation_button.grid()
        self.root.configure(menu=self._architecture_menu)
        self._layout_workbench_header()

    def _apply_unit_config(self, app):
        editor = self._editor
        identity = editor['id']
        try:
            config = app._config_dict()
            current = model.unit_by_id(self.project, identity)
            if config == editor['applied_config'] and current['spec'] == editor['spec']:
                return True
            detached = model.set_unit_config(self.project, identity, config)
        except Exception as error:
            self._save_state.set('请修正单元参数')
            messagebox.showerror('单元参数', '参数未能应用到工程：\n' + str(error), parent=self.root)
            field = getattr(error, 'input_widget', None)
            if field is not None and field.winfo_ismapped():
                field.focus_set()
                if isinstance(field, ttk.Entry):
                    field.selection_range(0, 'end')
            return False
        editor['spec'] = copy.deepcopy(model.unit_by_id(self.project, identity)['spec'])
        editor['applied_config'] = copy.deepcopy(config)
        self._unit_graph_changed = True
        if detached:
            self._unit_detached.update(detached)
            self._save_state.set('输出端口减少，已断开：' + '、'.join(detached))
        elif self.project != self._project_baseline:
            self._save_state.set('已应用到当前工程 · 待保存文件')
        return True

    def back_to_architecture(self, app=None):
        app = self.calculator if app is None else app
        if app is None or app is not self.calculator:
            return False
        center = getattr(app, '_simulation_center', None)
        if center and not center.closed and center.running():
            self._save_state.set('单元仿真运行中 · 完成或取消后可返回')
            return False
        if not self._apply_unit_config(app):
            return False
        if center and not center.closed:
            center.close()
        identity = self._editor['id']
        if hasattr(app, 'selected_result_page'):
            self._unit_page_states[identity] = app.selected_result_page()
        self.calculator = None
        self._editor = None
        app.container.grid_remove()
        self._architecture.grid()
        self._show_architecture_header()
        previous_selection = self.selected
        self.selected = ('unit', identity)
        note = '单元设计已应用到当前工程。'
        if self._unit_detached:
            note += '输出端口减少，已断开：' + '、'.join(sorted(self._unit_detached))
        if self._unit_graph_changed or self._unit_active_changed:
            self.changed(note)
        else:
            self._refresh_save_state()
            self.status.set(note)
        if self._unit_graph_changed:
            self.render()
        elif previous_selection != self.selected:
            from system_canvas import update_selection
            update_selection(self, previous_selection)
            self.show_inspector()
        for view, move, position in zip((self.canvas.xview, self.canvas.yview),
                                        (self.canvas.xview_moveto, self.canvas.yview_moveto),
                                        self._canvas_view):
            if view()[0] != position:
                move(position)
        self.canvas.focus_set()
        if self._system_simulation_return:
            restore, self._system_simulation_return = self._system_simulation_return, None
            self.root.after_idle(restore)
        return True

    def _release_editor(self, identity):
        editor = self._editors.pop(identity, None)
        if editor is None:
            return
        if editor is self._editor:
            self._editor = None
        app = editor['app']
        if hasattr(app, 'dispose'):
            app.dispose()
        menu = getattr(app, 'workspace_menu', None)
        if menu is not None:
            menu.destroy()
        app.container.destroy()

    def _reset_unit_views(self):
        if self._opening_unit is not None:
            self.root.after_cancel(self._opening_unit)
            self._opening_unit = None
            self._opening_view.grid_remove()
        for identity in tuple(self._editors):
            self._release_editor(identity)
        self._unit_page_states.clear()

    def calculate_current(self):
        app = self.calculator
        if app is None:
            return
        if hasattr(app, 'request_update'):
            app.request_update()
        else:
            app.compute()

    def open_current_simulation(self):
        if self.calculator is None:
            self.show_sequence()
        elif hasattr(self.calculator, '_open_simulation_center'):
            self.calculator._open_simulation_center()

    def open_current_config(self):
        if self.calculator is None:
            self.open_file()
        elif hasattr(self.calculator, 'load_config'):
            self.calculator.load_config()

    def export_current_report(self):
        if self.calculator is None:
            self.export_report()
        elif hasattr(self.calculator, '_export_report_ui'):
            self.calculator._export_report_ui()
        else:
            self.calculator.report('docx')

    def close(self):
        if self.calculator is not None:
            center = getattr(self.calculator, '_simulation_center', None)
            if center and not center.closed and center.running():
                center.close()
                self._save_state.set('正在停止仿真，运行日志会保留')
                self.root.after(150, self.close)
                return
            if not self.back_to_architecture():
                return
        if not self.save_inspector():return
        if self._sequence_dialog and self._sequence_dialog.job is not None:
            self._sequence_dialog.close()
            self.status.set('正在停止联合启停仿真，停止后关闭画布。')
            self.root.after(150,self.close)
            return
        if self.report_process and self.report_process.is_alive():
            self.report_stop.set()
            self.report_process.terminate()
            self.report_process.join(timeout=1)
        self.rename_project()
        self._reset_unit_views()
        self.root.destroy()

    def show_sequence(self):
        if not self.save_inspector():return
        try:
            from simulation_center import show
            return show(self, 'sequence', system=True)
        except Exception as error:
            messagebox.showerror('联合启停仿真',str(error),parent=self.root)

    def export_report(self):
        if self.report_process and self.report_process.is_alive():
            self.report_stop.set()
            self.status.set('正在取消报告，当前单元完成后停止。')
            return
        if not list(model.all_nodes(self.project)):
            self.status.set('请先增加至少一个节点。')
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='导出系统与所有电源模块报告', initialfile=self.project['title'] + '报告包.zip', defaultextension='.zip', filetypes=[('ZIP', '*.zip')])
        if not path:
            return
        from system_report_worker import export_system_report
        ctx = multiprocessing.get_context('spawn')
        self.report_events, self.report_stop = ctx.Queue(), ctx.Event()
        self.report_process = ctx.Process(target=export_system_report, args=(copy.deepcopy(self.project), path, self.report_events, self.report_stop), daemon=True)
        self.report_process.start()
        self.report_button.configure(text='取消报告')
        self.status.set('正在生成系统报告。可继续查看架构。')
        self.root.after(150, self.poll_report)

    def poll_report(self):
        finished = False
        try:
            while True:
                kind, payload = self.report_events.get_nowait()
                if kind == 'progress':
                    self.status.set('报告生成：' + payload)
                elif kind == 'done':
                    finished = True
                    successful, total = payload['successful'], payload['total']
                    status = '已导出系统报告' if successful == total else '已导出部分系统报告'
                    self.status.set(f"{status}。{successful}/{total} 个单元的报告完整。\n{payload['path']}")
                elif kind in ('error', 'cancelled'):
                    finished = True
                    self.status.set('报告：' + str(payload))
        except queue.Empty:
            pass
        if not finished and self.report_process.is_alive():
            self.root.after(200, self.poll_report)
        else:
            if not finished:
                self.status.set('报告进程已结束，请检查输出或重试。')
            self.report_button.configure(text='导出系统报告')
            self.report_process.join(timeout=.1)
