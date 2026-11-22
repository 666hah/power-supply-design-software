"""LLC symbols and the physical reference-designator registry."""

from tkinter import Canvas, ttk

from capacitor_banks import bank
from power_stage import fmt_eng


def llc_controller_reference(p):
    hhc = p.get('control_mode') == 'Hybrid Hysteretic'
    item = ((p.get('component_management') or {}).get('items') or {}).get('U_CTRL') or {}
    identity = ' '.join(str(item.get(key) or '').strip() for key in ('manufacturer', 'model')).strip()
    fields = ['llc_fmin', 'llc_fmax', 'llc_dead_time', 'llc_kp', 'llc_ki', 'llc_ocp',
              'llc_soft_start', 'llc_uvlo', 'llc_ovp']
    if hhc:
        fields.extend(('llc_hhc_sense', 'llc_hhc_ramp'))
    mode = '混合滞环 · Cr 采样与斜坡' if hhc else '电压调频 · VCO'
    return dict(ref='U_CTRL', kind='controller', role='LLC 控制器行为参考',
                values=' · '.join(x for x in (identity, mode) if x), keys=tuple(fields))


def llc_component_rows(p):
    rows = []

    def add(ref, kind, role, fields=(), values=None):
        if values is None:
            values = ' / '.join(f'{key}={fmt_eng(p[key], unit)}' for key, unit in fields if key in p)
        rows.append(dict(ref=ref, kind=kind, role=role, values=values, keys=tuple(key for key, _ in fields)))

    add('J1', 'connector', '直流母线输入端口', [('V_in', 'V')])
    if p.get('d_in_enable'):
        add('D_IN', 'diode', '输入防反二极管', [('Vf_din', 'V')])
    for index, c in enumerate(bank(p, 'input'), 1):
        add(f'C_IN{index}', 'capacitor', f'输入并联电容 {index}',
            values=' / '.join(fmt_eng(c[k], u) for k, u in (('C', 'F'), ('ESR', 'Ω'), ('ESL', 'H'))))
    switch_roles = ('左桥臂高侧', '左桥臂低侧', '右桥臂高侧', '右桥臂低侧')
    for index, role in enumerate(switch_roles[:4 if p.get('llc_bridge') == 'full' else 2], 1):
        add(f'Q{index}', 'mos', role+' N-MOS，桥臂共用模型参数',
            [('Rds_on', 'Ω'), ('Qg', 'C'), ('Coss', 'F'), ('llc_qoss', 'C')])
    add('L_R', 'magnetic', '原边等效串联谐振电感，含计入的漏感',
        [('llc_lr', 'H'), ('llc_tank_r', 'Ω')])
    add('C_R', 'capacitor', '串联谐振电容', [('llc_cr', 'F')])
    add('T1', 'magnetic', '隔离变压器与励磁支路', [('N', ''), ('llc_lm', 'H')])
    for index in range(1, 5):
        add(f'D{index}', 'diode', '副边桥式整流二极管，共用模型参数',
            [('Vf_diode', 'V'), ('llc_rect_r', 'Ω'), ('llc_diode_cj', 'F')])
    for index, c in enumerate(bank(p), 1):
        add(f'C_O{index}', 'capacitor', f'输出并联电容 {index}',
            values=' / '.join(fmt_eng(c[k], u) for k, u in (('C', 'F'), ('ESR', 'Ω'), ('ESL', 'H'))))
    if p.get('d_out_enable'):
        add('D_OUT', 'diode', '输出防反二极管', [('Vf_dout', 'V')])
    add('J2', 'connector', '输出端口', [('V_out', 'V'), ('P_out', 'W')])
    add('R_LOAD', 'load', '端口等效负载', [('P_out', 'W')])
    rows.append(llc_controller_reference(p))
    if ((p.get('component_management') or {}).get('items') or {}).get('U_FB'):
        add('U_FB', 'feedback', '副边取样与隔离反馈参考',
            [('V_out', 'V'), ('llc_kp', ''), ('llc_ki', '')], values='副边电容端 → 隔离反馈 → 控制器')
    return rows


def draw_llc(ax, p, solved, show_values, interactive, hits, *, control_ports=False, control_anchors=None):
    from topology_diagram import _Schematic, _expand_banks

    full = p.get('llc_bridge') == 'full'
    incoming, outgoing = bank(p, 'input'), bank(p)
    input_slot, output_slot = (2.6, 4.55), (32.05, 34.3)
    expansion = _expand_banks((input_slot, len(incoming)), (output_slot, len(outgoing))) if interactive else ()
    s = _Schematic(ax, interactive=interactive, hits=hits, expansion=expansion, control_anchors=control_anchors)
    ax.clear()
    ax.set_aspect('equal')
    ax.set_xlim(-.35, s.x(41.4))
    ax.set_ylim(-.58 if control_ports else -2.15, 12.45)
    ax.set_axis_off()
    refs = {row['ref'] for row in llc_component_rows(p)}

    vin, pgnd = 10.7, 1.
    sw_a, sw_b = 6.15, 4.13
    with s.mark('J1'):
        s.terminal(.25, vin)
        s.terminal(.25, pgnd)
        s.text(.55, 11.90, 'J1 · Vin +')
        s.text(.3, .35, '−')
    xlast = 10.05 if full else 6.3
    s.wire((.25, pgnd), (10.05 if full else 18.6, pgnd))
    if 'D_IN' in refs:
        a, b = s.diode(1.35, vin, 'D_IN')
        s.wire((.25, vin), a)
        s.wire(b, (xlast, vin))
    else:
        s.wire((.25, vin), (xlast, vin))
    s.capacitor_bank(incoming, [f'C_IN{i}' for i in range(1, len(incoming)+1)],
                     input_slot, vin, pgnd)
    d, source = s.mos(6.3, 8.45, 'Q1')
    lower_d, lower_source = s.mos(6.3, 2.8, 'Q2')
    s.wire((6.3, vin), d)
    s.wire(source, lower_d)
    s.wire(lower_source, (6.3, pgnd))
    s.node(6.3, sw_a)
    s.text(6.88, sw_a+.33, 'SW_A', fontsize=7)
    if control_ports:
        s.port('PGND', (1.7, pgnd), (1.7, pgnd-.24), side='bottom')
        s.drive_ports(6.3, 8.45, 'Q1', source, controller_ref='U_CTRL',
                      gate_escape=((4.8, -.68),))
        s.drive_ports(6.3, 2.8, 'Q2', lower_source, controller_ref='U_CTRL',
                      gate_dx=-1.26, gate_escape=((5.04, -.68),))
    else:
        s.text(5.8, .3, 'PGND', fontsize=8)
    if full:
        d, source = s.mos(10.05, 8.45, 'Q3')
        lower_d, lower_source = s.mos(10.05, 2.8, 'Q4')
        s.wire((10.05, vin), d)
        # In the desktop drawing the hump is SW_A and the underpassing wire is SW_B.
        if control_ports:
            s.wire(source, (10.05, sw_a+.39))
            s.wire((10.05, sw_a+.21), lower_d)
            s.drive_ports(10.05, 8.45, 'Q3', source, controller_ref='U_CTRL', gate_lift=.67,
                          gate_escape=((8.55, -.68),))
            s.drive_ports(10.05, 2.8, 'Q4', lower_source, controller_ref='U_CTRL', gate_lift=.67,
                          gate_dx=-1.26, gate_escape=((8.79, -.68),))
        else:
            s.wire(source, (10.05, sw_a+.26))
            s.wire((10.05, sw_a-.26), lower_d)
        s.wire(lower_source, (10.05, pgnd))
        s.node(10.05, sw_b)
        s.text(10.8, sw_b-.43, 'SW_B', fontsize=7)
        s.node(6.3, vin)
        s.node(6.3, pgnd)

    if control_ports:
        # Match the controller's differential Cr probe in the LLC deck.
        ca, cb = s._part((12.4, sw_a), (1, 0), 'C_R', 'capacitor')
        la, lb = s.inductor(14.55, sw_a, 'L_R')
        if full:
            import math
            hump = [(10.05+.30*math.cos(angle), sw_a+.30*math.sin(angle))
                    for angle in (math.pi*(1-i/12) for i in range(13))]
            s.wire((6.3, sw_a), *hump, ca)
        else:
            s.wire((6.3, sw_a), ca)
        s.wire(cb, la)
        s.wire(lb, (18.6, sw_a))
        if p.get('control_mode') == 'Hybrid Hysteretic':
            s.port('V_CR+', ca, (ca[0]-.25, sw_a-.41), side='bottom')
            s.port('V_CR−', cb, (cb[0]+.18, sw_a-.41), side='bottom')
        if p.get('llc_ocp', 0.) > 0:
            s.current_probe(14.55, sw_a+1.16, 'I_LR')
    else:
        la, lb = s.inductor(12.4, sw_a, 'L_R')
        ca, cb = s._part((14.55, sw_a), (1, 0), 'C_R', 'capacitor')
        s.wire((6.3, sw_a), la)
        s.wire(lb, ca)
        s.wire(cb, (18.6, sw_a))
    lower_primary = 4.65
    with s.mark('T1'):
        s.inductor(18.6, 5.40, None, direction=(0, 1))
        s.inductor(22.15, 5.40, None, direction=(0, 1))
        s.wire((20.12, 4.57), (20.12, 6.25))
        s.wire((20.39, 4.57), (20.39, 6.25))
        s.node(18.96, 6.37)
        s.node(21.88, 6.37)
        s.text(20.38, 7.20, 'T1 · Np/Ns')
    # Lm belongs to T1; it has no independent BOM entry.
    with s.mark('T1'):
        s.inductor(16.82, 5.40, None, direction=(0, 1))
        s.text(16.48, 5.33, 'Lm', ha='right')
    s.node(16.82, sw_a)
    s.wire((16.82, lower_primary), (18.6, lower_primary))
    s.node(16.82, lower_primary)
    if full:
        s.wire((10.05, sw_b), (16.82, sw_b), (16.82, lower_primary))
    else:
        s.wire((18.6, lower_primary), (18.6, pgnd))
    s.wire((20.25, .3), (20.25, 4), color='#b7c6d7', lw=.9, ls='--')
    s.wire((20.25, 7.62), (20.25, 10.8), color='#b7c6d7', lw=.9, ls='--')
    s.text(20.25, -.13, '原副边隔离', fontsize=8, color='#7890a6')

    rect_pos, rect_neg = 9.37, 1.55
    ac_left, ac_right = 25.0, 29.5
    s.wire((22.15, sw_a), (ac_left, sw_a))
    s.wire((22.15, lower_primary), (ac_right, lower_primary))
    for index, x in enumerate((ac_left, ac_right)):
        mid = sw_a if index == 0 else lower_primary
        a, b = s.diode(x, 7.7, f'D{index*2+1}', direction=(0, 1), label_side=-1)
        c, h = s.diode(x, 3.03, f'D{index*2+2}', direction=(0, 1), label_side=-1)
        s.wire(b, (x, rect_pos))
        s.wire(a, (x, mid))
        if index == 0:
            s.wire((x, mid), (x, lower_primary+.23))
            s.wire((x, lower_primary-.23), h)
        else:
            s.wire((x, mid), h)
        s.wire(c, (x, rect_neg))
        s.node(x, mid)
    s.wire((ac_left, rect_pos), (36.35, rect_pos))
    s.wire((ac_left, rect_neg), (40.2, rect_neg))
    s.node(ac_right, rect_pos)
    s.node(ac_right, rect_neg)
    s.capacitor_bank(outgoing, [f'C_O{i}' for i in range(1, len(outgoing)+1)],
                     output_slot, rect_pos, rect_neg)
    if 'D_OUT' in refs:
        a, b = s.diode(37.2, rect_pos, 'D_OUT')
        s.wire((36.35, rect_pos), a)
        s.wire(b, (40.2, rect_pos))
    else:
        s.wire((36.35, rect_pos), (40.2, rect_pos))
    a, b = s.resistor(38.9, 5.3, 'R_LOAD')
    s.wire((38.9, rect_pos), b)
    s.wire(a, (38.9, rect_neg))
    s.node(38.9, rect_pos)
    s.node(38.9, rect_neg)
    with s.mark('J2'):
        s.terminal(40.2, rect_pos)
        s.terminal(40.2, rect_neg)
        s.text(39.35, 10.51, 'J2 · Vout +')
        if not control_ports:
            s.text(40.2, .9, 'SGND', fontsize=8)
    if control_ports:
        feedback_ref = 'U_FB' if 'U_FB' in refs else None
        lift = .48 if control_anchors is not None else .35
        s.port('V_SENSE', (36.35, rect_pos), (36.35, rect_pos+lift), ref=feedback_ref,
               escape=((41.85, rect_pos+lift),))
        s.port('SGND', (36.35, rect_neg), (36.35, rect_neg-.28), side='bottom', ref=feedback_ref)
    else:
        with s.mark('U_CTRL'):
            s.wire((5, -1.63), (18.1, -1.63), (18.1, -.18), (5, -.18), (5, -1.63),
                   color='#7395b5', lw=1.)
            controller = ((p.get('component_management') or {}).get('items') or {}).get('U_CTRL') or {}
            mode = 'HHC' if p.get('control_mode') == 'Hybrid Hysteretic' else '电压变频'
            label = ' · '.join(val for val in ('U_CTRL',controller.get('model','')[:21],mode) if val)
            s.text(11.55, -.91, label, fontsize=8)
        if 'U_FB' in refs:
            with s.mark('U_FB'):
                s.wire((22.25, -1.63), (34.1, -1.63), (34.1, -.18), (22.25, -.18), (22.25, -1.63),
                       color='#7395b5', lw=1.)
                s.text(28.15, -.91, 'U_FB · 输出电容端隔离取样', fontsize=8, color='#567894')
        else:
            s.text(28.15, -1.02, 'SSR 采样：输出防反管前电容端', fontsize=8, color='#567894')
    if show_values and solved and solved.get('f_sw'):
        s.text(15.27, 11.61, '实际开关频率 '+fmt_eng(solved['f_sw'], 'Hz'), fontsize=8)
    assert s.refs == refs, (s.refs-refs, refs-s.refs)


class SimulationLogicPanel(ttk.Frame):
    """Resizable LLC block diagram and explanations for the experiment inputs."""

    _HELP = {
        'enable_delay_ms': '从仿真时间零点到外部使能的延时。使能后按设计参数中的软启动时序运行。',
        'step_ms': '负载开始跳变的时间。应留出启动和初始负载收敛所需的时间。',
        'stop_ms': '时域观察终点。时域数据用于启动、应力和载荷变化后的恢复统计。',
        'simulation_threads': '每个 LTspice 工况可使用的逻辑线程上限。',
        'simulation_timeout_s': '一个时域工况允许运行的最长时间。超时会保留失败状态和原因。',
        'comparison_tolerance_pct': '软件计算值与开关仿真值对比时使用的相对偏差阈值。',
        'include_cap_esl': '为输入和输出电容支路加入已配置的 ESL，用于观察更快的边沿与尖峰。',
        'fra_enabled': '在稳态工作点附近进行开关级频率响应测量，并与计算得到的环路对比。',
        'fra_start_hz': '开关级频率响应的起始注入频率。',
        'fra_stop_hz': '开关级频率响应的最高注入频率。扫描须落在计算环路和仿真的有效频带内。',
        'fra_oct': '每倍频程的注入频点数。增加密度会增加开关仿真时长。',
        'fra_amplitude_pct': '主要注入信号的幅度。另以较小幅值复核同一频点的线性程度。',
        'fra_timeout_s': '单项开关级频率响应试验允许运行的最长时间。',
    }

    def __init__(self, parent, parameters):
        super().__init__(parent, padding=(10, 0, 0, 0), width=640)
        from PIL import Image
        from docs.llc_control_diagrams import render_llc_control
        from llc_settings import effective

        self.parameters = effective(parameters)
        self._active = None
        self._resize_job = None
        self._image_size = None
        self._photo = None
        self._zoom = 1.
        with Image.open(render_llc_control(self.parameters['control_mode'])) as diagram:
            self._figure = diagram.copy()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        ttk.Label(head, text='LLC 控制器功能框图', style='Param.TLabel').pack(side='left')
        for label, factor in (('适合窗口', None), ('+', 1.2), ('−', 1/1.2)):
            ttk.Button(head, text=label, width=10 if factor is None else 3,
                       command=lambda f=factor:self._resize(f)).pack(side='right', padx=(3, 0))
        view = ttk.Frame(self)
        view.grid(row=3, column=0, sticky='nsew')
        view.columnconfigure(0, weight=1)
        view.rowconfigure(0, weight=1)
        self.canvas = Canvas(view, width=390, height=205, highlightthickness=1,
                             highlightbackground='#b5c5d3', background='white')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        xbar = ttk.Scrollbar(view, orient='horizontal', command=self.canvas.xview)
        ybar = ttk.Scrollbar(view, orient='vertical', command=self.canvas.yview)
        xbar.grid(row=1, column=0, sticky='ew')
        ybar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self._picture = self.canvas.create_image(0, 0, anchor='nw')
        self.canvas.bind('<Configure>', self._schedule_resize)
        self.canvas.bind('<ButtonPress-1>', lambda event:self.canvas.scan_mark(event.x, event.y))
        self.canvas.bind('<B1-Motion>', lambda event:self.canvas.scan_dragto(event.x, event.y, gain=1))
        self.spec = ttk.Label(self, style='ResultConclusion.TLabel', justify='left', wraplength=555)
        self.spec.grid(row=1, column=0, sticky='ew', pady=(0, 4))
        self.description = ttk.Label(self, style='Muted.TLabel', justify='left', wraplength=555)
        self.description.grid(row=2, column=0, sticky='ew', pady=(0, 4))
        self.bind('<Configure>', self._wrap, add='+')
        self.bind('<Destroy>', self._cancel_resize, add='+')
        self.refresh()

    def _wrap(self, event):
        if event.widget is self:
            width = max(180, event.width - 22)
            for label in (self.spec, self.description):
                label.configure(wraplength=width)

    def _cancel_resize(self, event):
        if event.widget is self and self._resize_job is not None:
            self.after_cancel(self._resize_job)
            self._resize_job = None

    def _schedule_resize(self, _event=None):
        if self._resize_job is None:
            self._resize_job = self.after(40, self._draw)

    def _resize(self, factor):
        self._zoom = 1. if factor is None else min(4., max(.65, self._zoom * factor))
        self._schedule_resize()

    def _draw(self):
        from PIL import Image, ImageTk

        self._resize_job = None
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if min(width, height) <= 10:
            return
        fw, fh = self._figure.size
        scale = min(1., min((width-12)/fw, (height-12)/fh) * self._zoom)
        size = max(1, round(fw*scale)), max(1, round(fh*scale))
        if size != self._image_size:
            canvas_image = self._figure.resize(size, Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(canvas_image, master=self.canvas)
            self.canvas.itemconfigure(self._picture, image=self._photo)
            self._image_size = size
        self.canvas.coords(self._picture, max(6, (width-size[0])/2), max(6, (height-size[1])/2))
        self.canvas.configure(scrollregion=(0, 0, max(width, size[0]+12), max(height, size[1]+12)))
        if self._zoom == 1.:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)

    def select(self, key):
        self._active = key if key in self._HELP else None
        self.refresh()

    def refresh(self):
        from spice_export import SETTINGS

        p = self.parameters
        bridge = '半桥' if p['llc_bridge'] == 'half' else '全桥'
        freq = f"{fmt_eng(p['llc_fmin'], 'Hz')}–{fmt_eng(p['llc_fmax'], 'Hz')}"
        tank = ' · '.join(f"{label} {fmt_eng(p[key], unit)}" for label, key, unit in
                          (('Lr', 'llc_lr', 'H'), ('Cr', 'llc_cr', 'F'), ('Lm', 'llc_lm', 'H')))
        self.spec.configure(text=f"{bridge} · 开关频率 {freq} · 桥臂死区 {fmt_eng(p['llc_dead_time'], 's')}\n"
                                 f"{tank} · 原副边匝比 {p['N']:.4g}:1")
        key = self._active
        context = f'{SETTINGS[key][3]}\n{self._HELP[key]}' if key in SETTINGS and key in self._HELP else (
            '仿真沿用当前桥式、谐振腔、外环和保护参数。选择左侧字段可查看用途。')
        self.description.configure(text=context)
        self._schedule_resize()
