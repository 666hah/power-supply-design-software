"""Desktop launch centre for a frozen, switched system start/stop experiment.

Only the Tk thread reads or changes widgets and the workspace. Workers receive
plain copies, send mailbox events, and own a cooperative cancellation event.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from scrollable_results import ScrollableResults
from system_sequence_config import normalize


# key, display label, SI units per display unit, input kind, explanation
SETTINGS = (
    ('stop_s', '仿真终止时间 / ms', .001, 'number', '从 t=0 保留完整启停过程。'),
    ('timeout_s', '运行超时 / s', 1., 'number', '超时停止本次任务，保留日志。'),
    ('threads', 'LTspice 线程数', 1., 'integer', '仅设置求解线程数，不改变模型精度。'),
    ('vin_case', '输入端点', 1., ('min', 'max'), '同一套硬件选择 Vinmin 或 Vinmax。'),
    ('max_step_s', '最大步长 / µs（0=自动）', 1e-6, 'number', '0 使用运行器按开关频率选择的步长。'),
    ('include_switching_capacitance', 'Buck/Boost 保留器件寄生电容（推荐）', 1., 'boolean', '本轮联合模型默认启用，旧工程缺省也启用：使用各单元已填的 Coss、Qg 换算等效栅电容，Cj 来自控制器中的结电容假设。保留开关节点储能，减少 DCM 归零时零电容模型导致的数值卡顿；不表示实测或完整开关损耗模型。取消后沿用各单元独立仿真模式，若其关闭寄生电容，仍可能卡顿。仅作用于联合仿真，不改写单元设计。'),
)
SOURCE_FIELDS = (
    ('protection_mode', '外部源保护行为', 1., ('monitor', 'cc', 'foldback', 'hiccup'), '仅比较不会限制电流。其他模式按配置改变实际供流，属于行为模型；须核实真实电源的保护方式。'),
    ('on_s', '输入开始上升 / ms', .001, 'number', '本输入源的独立启动时刻。'),
    ('rise_s', '上升时间 / ms', .001, 'number', ''),
    ('off_s', '输入开始下降 / ms', .001, 'number', '本输入源的独立关断时刻。'),
    ('fall_s', '下降时间 / ms', .001, 'number', ''),
    ('resistance_ohm', '源串联电阻 / mΩ', .001, 'number', '默认 50 mΩ 是工程假设，请按电源/线缆核实。'),
    ('inductance_H', '源串联电感 / µH', 1e-6, 'number', '0 表示本轮未声明源寄生电感。'),
    ('output_capacitance_F', '外部源端输出电容 / µF', 1e-6, 'number', '位于外部源限流/阻断后的输出端口，区别各转换器已有 Cin，避免重复填写。0=本轮未建模，不是实物没有电容；须按规格或实测填写。'),
    ('output_esr_ohm', '外部源端输出电容 ESR / Ω', 1., 'number', '默认 0.1 Ω 只是工程初值；0 表示理想电容，不会自动改成其他阻值。只有上项电容大于 0 时装入电路。'),
    ('current_limit_A', '源限流 / A（留空=未知）', 1., 'optional', '未知不能作为限流能力通过的依据。'),
    ('foldback_short_A', '折返短路电流 / A', 1., 'optional', '仅折返模式生效；输出接近零时可供电流。须来自规格或实测。'),
    ('trip_delay_s', '连续限流后保护延时 / ms', .001, 'number', '仅打嗝模式生效；持续限流达到此时间后关断。'),
    ('retry_s', '打嗝关断等待 / ms', .001, 'number', '仅打嗝模式生效；等待结束后重新尝试供电。'),
    ('sink_current', '允许外部源吸收回流', 1., 'boolean', '默认关闭：源端理想阻断，关断后不吸收回流。启用表示可充电电池或四象限源可吸收电容能量；须核实实际源能力，属于工程假设。'),
)
UNIT_FIELDS = (
    ('enable_s', 'EN 最早允许启动 / ms', .001, 'number', '还须满足已填写的输入 UVLO 和等待端口条件。'),
    ('disable_s', 'EN 关断 / ms', .001, 'number', ''),
    ('vin_on_V', '输入 UVLO 开启阈值 / V', 1., 'optional', '在输入防反后的母线检测；留空=未知。'),
    ('vin_off_V', '输入 UVLO 关闭阈值 / V', 1., 'optional', '留空=未知；与控制器 VCC 欠压阈值不同。'),
    ('soft_start_s', '软启动时间 / ms（留空=未知）', .001, 'optional', '开关单元留空沿用已配置控制器；LDO填写后按线性参考爬升，仅为行为近似。'),
    ('vcc_mode', '控制器偏置供电', 1., ('ideal', 'enable_follow'), 'ideal=独立理想 VCC；enable_follow=理想 VCC 跟随 EN。均非辅助供电启动模型。'),
    ('wait_for_port', '等待端口电压有效（外部 PG 近似）', 1., 'port', '留空=不等待。填写如 PSU-01/OUT1；这是外部电压监控，不是真实 PG 开漏引脚。可在多轨就绪条件中再添加约束。'),
    ('pg_threshold_V', '等待端口 PG 阈值 / V', 1., 'optional', '指定等待端口时须填写阈值；留空=未知。'),
    ('pg_hysteresis_V', 'PG 恢复迟滞 / V', 1., 'number', '有效后跌到“PG阈值−迟滞”才失效；迟滞须小于PG阈值。0 无迟滞，负载变化或电压恢复时可能反复启停。'),
    ('pg_delay_s', '全部就绪后连续等待 / ms', .001, 'number', '旧等待端口与多轨就绪条件共同约束启动。任一掉压条件失效后重新计时。'),
)
LDO_FIELDS = (
    ('ldo_output_current_limit_A', 'LDO 输出限流 / A（留空=未知）', 1., 'optional', '须来自器件资料或实测；不会把额定输出电流当作保护点。'),
    ('ldo_output_resistance_ohm', 'LDO 输出等效电阻 / Ω', 1., 'number', '默认 0.1 Ω 是行为模型工程假设；不表示器件已验证。'),
)
LOAD_FIELDS = (
    ('enabled', '启用此负载', 1., 'boolean', '独立控制额外负载；单元本身的真实 Cin/Cout 始终保留。'),
    ('mode', '负载方式', 1., ('R', 'I', 'P'), 'R=恒阻，I=恒流，P=恒功率；由额定功率和额定电压定义。启用 I/P 时必须填写正的开启/关闭耗功门限。'),
    ('power_W', '额定功率 / W', 1., 'number', ''),
    ('nominal_voltage_V', '额定电压 / V（0=自动）', 1., 'number', '用于 R/I/P 定义；0 从所接端口解析。'),
    ('on_V', '负载开启阈值 / V', 1., 'optional', 'I/P 必须为正值，且高于关闭阈值；R 可与关闭阈值一起留空。'),
    ('off_V', '负载关闭阈值 / V', 1., 'optional', 'I/P 必须为正值；与开启阈值组成滞回，低于此点退出额定耗功。'),
    ('delay_s', '全部就绪后复位释放延时 / ms', .001, 'number', '本地门限和多轨条件必须连续满足；失效则复位计时与运行阶段。'),
    ('ramp_s', '负载建立时间 / ms', .001, 'number', ''),
    ('off_current_A', '负载待机电流 / A', 1., 'number', '未耗功时的待机耗流；建立负载时平滑过渡，运行后不再额外叠加。低压段线性缩放为工程假设：上限取关闭阈值，无阈值时取不高于 1 V 的参考电压。'),
    ('input_capacitance_F', '额外输入电容 / µF', 1e-6, 'number', '仅表示用户声明的额外电容；不重复添加电源 Cin/Cout。'),
    ('input_esr_ohm', '额外电容 ESR / mΩ', .001, 'number', '默认 100 mΩ 是未核实的工程假设。'),
    ('bleeder_ohm', '额外泄放电阻 / Ω（留空=无）', 1., 'optional', '需模拟泄放时显式填写。'),
)
EDGE_FIELDS = (
    ('resistance_ohm', '支路串联电阻 / mΩ', .001, 'number', '默认 10 mΩ 是工程假设，请按连接与线缆核实。'),
    ('inductance_H', '支路串联电感 / µH', 1e-6, 'number', '0 表示本轮未声明支路寄生电感。'),
)

PROTECTION_LABELS = {
    'monitor': 'monitor · 仅比较门限，不限流',
    'cc': 'cc · 恒流限制',
    'foldback': 'foldback · 电压相关折返',
    'hiccup': 'hiccup · 限流后打嗝重试',
}

LIST_FIELDS = {
    'voltage_profile': (
        ('time_s', '时间 / ms', .001, 'number', ''),
        ('level', '输入电压倍率', 1., 'number', '1=所选 Vin 端点，0=掉电；相邻点之间线性变化。'),
    ),
    'ready_conditions': (
        ('port', '监测端口', 1., 'port', '所有条件与本地门限同时满足才允许开始计时。'),
        ('on_V', '开启阈值 / V', 1., 'number', ''),
        ('off_V', '关闭阈值 / V', 1., 'number', '须低于开启阈值，形成迟滞。'),
    ),
    'stages': (
        ('name', '阶段名称', 1., 'text', '如固件启动、通信投入、正常运行；名称随报告保存。'),
        ('after_s', '复位释放后开始 / ms', .001, 'number', '相对全部条件连续满足且复位延时结束的时间，首阶段须为0。'),
        ('mode', '本阶段负载方式', 1., ('R', 'I', 'P'), 'R=恒阻，I=恒流，P=恒功率；I/P需正的本地耗功启停门限。'),
        ('power_W', '本阶段总运行功率 / W', 1., 'number', '基于负载额定电压定义，是该阶段的总需求，不是增量。'),
        ('ramp_s', '过渡到此阶段 / ms', .001, 'number', '从上一阶段需求平滑过渡；不得越过下一阶段开始时间。'),
    ),
}
LIST_TITLES = {'voltage_profile': '多次上电与掉电', 'ready_conditions': '多轨就绪与复位条件', 'stages': '分阶段负载'}
LIST_SUMMARIES = {
    'voltage_profile': '按时间编辑电压倍率；非空列表覆盖单次斜坡。',
    'ready_conditions': '全部条件同时满足才就绪；任一路失效即复位。',
    'stages': '阶段按复位释放后的相对时间执行，均为总功耗。',
}
LIST_NOTES = {
    'voltage_profile': '列表非空时覆盖单次上升/下降设置。第一点时间须为0，时间严格递增；最后一点之后保持该倍率。可配置短暂掉电和再次上电，电路电容不会被人为清零。',
    'ready_conditions': '全部条件按 AND 联动；任一路跌破关闭阈值，撤销就绪并重新计时。仅模拟配置的外部电压监控，不声称复刻真实芯片 PG、上拉电源或复位监督器。',
    'stages': '列表非空时替代固定运行功率与单次建立时间。先等待本地/多轨电压条件和复位释放延时，再依次进入阶段；掉压退回待机并重新启动。输入电容和泄放仍保持连接。参数须有资料或实测依据。',
}


def _observed_limits(summary):
    """Summarize available comparisons without counting unknown results as passes."""
    if not isinstance(summary, dict):
        return ''
    source_checks = [row.get('current_limit_exceeded') for row in summary.get('sources') or ()]
    unit_checks = [((row.get('ocp') or {}).get('cycle_limit') or {}).get('hit') for row in summary.get('units') or ()]
    phrases = []
    for title, values in (('输入源超过限流门限', source_checks), ('单元观察到逐周期限流', unit_checks)):
        known = [value for value in values if isinstance(value, bool)]
        if known:
            text = f'{title} {sum(known)}/{len(known)}（已判定）'
            if len(known) < len(values):
                text += f'，另有 {len(values)-len(known)} 项待复核'
            phrases.append(text)
    return ' · '.join(phrases)


def _display(value, scale=1.):
    return '' if value is None else format(float(value) / scale, '.10g')


def _wrap(label):
    """Wrap within the actual viewport, including after a font/width change."""
    label.bind('<Configure>', lambda event: label.configure(wraplength=max(120, event.width-12)), add='+')
    return label


def _form(parent, fields, values, *, ports=()):
    variables = {}
    parent.sequence_field_boxes = {}
    parent.columnconfigure(0, weight=1)
    for row, (key, label, scale, kind, explanation) in enumerate(fields):
        box = ttk.Frame(parent, padding=(4, 5))
        box.grid(row=row, column=0, sticky='ew')
        parent.sequence_field_boxes[key] = box
        box.columnconfigure(0, weight=1)
        _wrap(ttk.Label(box, text=label, style='System.TLabel', wraplength=600)).grid(row=0, column=0, sticky='ew')
        value = values.get(key)
        if kind == 'boolean':
            variable = tk.BooleanVar(parent, bool(value))
            widget = ttk.Checkbutton(box, variable=variable, text='启用', style='System.TCheckbutton')
        else:
            value = PROTECTION_LABELS.get(value, value) if key == 'protection_mode' else value
            variable = tk.StringVar(parent, value if isinstance(kind, tuple) or kind in ('port', 'text') else _display(value, scale))
            if isinstance(kind, tuple) or kind == 'port':
                choices = tuple(PROTECTION_LABELS.values()) if key == 'protection_mode' else kind
                widget = ttk.Combobox(box, textvariable=variable, values=choices if isinstance(kind, tuple) else ('', *ports),
                                      state='readonly' if isinstance(kind, tuple) else 'normal', style='System.TCombobox',
                                      font=('Microsoft YaHei UI', -14), width=28)
            else:
                widget = ttk.Entry(box, textvariable=variable, style='System.TEntry', font=('Microsoft YaHei UI', -14), width=28)
        widget.grid(row=1, column=0, sticky='ew', pady=(3, 0))
        if explanation:
            _wrap(ttk.Label(box, text=explanation, style='System.TLabel', foreground='#5c6e83',
                      wraplength=640, justify='left')).grid(row=2, column=0, sticky='ew', pady=(3, 0))
        variables[key] = variable
    return variables


def _read_form(fields, variables):
    result = {}
    for key, label, scale, kind, _ in fields:
        value = variables[key].get()
        if kind == 'boolean':
            result[key] = bool(value)
        elif isinstance(kind, tuple) or kind in ('port', 'text'):
            result[key] = value.split(' · ', 1)[0].strip() if key == 'protection_mode' else value.strip()
        elif kind == 'optional' and not value.strip():
            result[key] = None
        else:
            try:
                number = float(value) * scale
            except (ValueError, TypeError) as error:
                raise ValueError(label + '须填写数值。') from error
            if not math.isfinite(number) or number < 0 or (kind == 'integer' and (number < 1 or not number.is_integer())):
                raise ValueError(label + ('须为正整数。' if kind == 'integer' else '须为有限、非负数值。'))
            result[key] = int(number) if kind == 'integer' else number
    return result


class SequenceListEditor:
    """Transactional, unit-aware list editor; never runs or modifies the canvas."""

    def __init__(self, owner, key):
        self.owner, self.dialog, self.key = owner, owner.dialog, key
        self.group, self.identity, _ = owner.records[owner.current]
        self.rows = copy.deepcopy(self.dialog.draft[self.group][self.identity].get(key, []))
        self.fields = LIST_FIELDS[key]
        self.selected = None
        self.closed = False
        self.win = tk.Toplevel(self.dialog.win)
        self.win.title(self.identity+' · '+LIST_TITLES[key])
        self.win.transient(self.dialog.win)
        width = min(1000, self.win.winfo_screenwidth()-90)
        height = min(800, self.win.winfo_screenheight()-180)
        self.win.geometry(f'{width}x{height}+20+10')
        self.win.minsize(min(700, width), min(500, height))
        self.win.protocol('WM_DELETE_WINDOW', self.cancel)
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Escape>', lambda _event: self.cancel())
        self.win.bind('<Control-Return>', lambda _event: self.save())
        self.status = tk.StringVar(self.win, '草稿 · 加入或更新条目后，点击「保存列表」。')
        body = ttk.Frame(self.win, padding=12)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        _wrap(ttk.Label(body, textvariable=self.status, style='ResultConclusion.TLabel', wraplength=850,
                       justify='left')).grid(row=0, column=0, sticky='ew', pady=(0, 5))
        _wrap(ttk.Label(body, text=LIST_SUMMARIES[key], style='System.TLabel', foreground='#5c6e83',
                       wraplength=850, justify='left')).grid(row=1, column=0, sticky='ew', pady=(0, 8))
        self.panes = ttk.Panedwindow(body, orient='vertical')
        self.panes.grid(row=2, column=0, sticky='nsew')
        self._pane_size = None
        self.panes.bind('<Configure>', self._layout_panes)
        table_box = ttk.Frame(self.panes)
        table_box.columnconfigure(0, weight=1)
        table_box.rowconfigure(0, weight=1)
        self.panes.add(table_box, weight=1)
        self.table = ttk.Treeview(table_box, columns=tuple(f[0] for f in self.fields),
                                  show='headings', height=4, selectmode='browse', style='Sequence.Treeview')
        short_labels = dict(time_s='时间 / ms', level='电压倍率', port='监测端口', on_V='开启 / V',
                            off_V='关闭 / V', name='阶段名称', after_s='开始 / ms', mode='方式',
                            power_W='总功率 / W', ramp_s='过渡 / ms')
        for field, label, _, _, _ in self.fields:
            self.table.heading(field, text=short_labels.get(field, label))
            self.table.column(field, width=210 if field in ('name', 'port') else 170,
                              minwidth=120, stretch=True)
        self.table.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(table_box, orient='vertical', command=self.table.yview)
        sx = ttk.Scrollbar(table_box, orient='horizontal', command=self.table.xview)
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        self.table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.table.bind('<<TreeviewSelect>>', self.select)
        self.scroll = ScrollableResults(self.panes)
        self.panes.add(self.scroll, weight=3)
        self.form = ttk.Frame(self.scroll.content)
        self.form.pack(fill='x')
        self.variables = _form(self.form, self.fields, self._default_row(), ports=self.dialog.ports)
        _wrap(ttk.Label(self.scroll.content, text=LIST_NOTES[key], style='System.TLabel',
                       foreground='#5c6e83', wraplength=850, justify='left')).pack(fill='x', pady=10)
        controls = ttk.Frame(body)
        controls.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        actions = (('加入新行', self.add), ('更新选中', self.update), ('删除选中', self.delete),
                   ('保存列表', self.save), ('取消', self.cancel))
        self.buttons = []
        for i, (title, command) in enumerate(actions):
            button = ttk.Button(controls, text=title, command=command,
                                style='SystemPrimary.TButton' if title == '保存列表' else 'System.TButton')
            button.grid(row=i//3, column=i%3, sticky='ew', padx=3, pady=3)
            controls.columnconfigure(i%3, weight=1)
            self.buttons.append(button)
        from ui_preferences import apply_studio_fonts
        apply_studio_fonts(self.win, int(self.dialog.font_choice.get()))
        self._refresh()
        self.sash_job = self.win.after_idle(self._initial_sash)
        self.win.grab_set()

    def _initial_sash(self):
        self.sash_job = None
        if not self.closed and self.panes.winfo_exists():
            self._layout_panes()

    def _layout_panes(self, _event=None):
        height = self.panes.winfo_height()
        size = int(self.dialog.font_choice.get())
        if height < 100 or self._pane_size == (height, size):
            return
        self._pane_size = (height, size)
        self.panes.sashpos(0, min(max(100, 2*size+50), height-70))

    def _default_row(self):
        if self.key == 'stages':
            last = max((r['after_s']+r['ramp_s'] for r in self.rows), default=-.001)
            return dict(name=f'阶段 {len(self.rows)+1}', after_s=max(0, last+.001), mode='R', power_W=0., ramp_s=.001)
        if self.key == 'voltage_profile':
            return dict(time_s=max((r['time_s'] for r in self.rows), default=-.001)+.001, level=0.)
        return dict(port='', on_V=0., off_V=0.)

    def _set_form(self, row):
        for key, _, scale, kind, _ in self.fields:
            self.variables[key].set(row[key] if isinstance(kind, tuple) or kind in ('port', 'text') else _display(row[key], scale))
        self._clean_form = {key: var.get() for key, var in self.variables.items()}

    def _refresh(self, select=None):
        self.table.delete(*self.table.get_children())
        for i, row in enumerate(self.rows):
            values = [row[key] if isinstance(kind, tuple) or kind in ('port', 'text') else _display(row[key], scale)
                      for key, _, scale, kind, _ in self.fields]
            self.table.insert('', 'end', iid=str(i), values=values)
        self.selected = select
        if select is not None:
            self.table.selection_set(str(select))
            self.table.see(str(select))
        self._set_form(self.rows[select] if select is not None else self._default_row())

    def select(self, _event=None):
        selected = self.table.selection()
        if selected and int(selected[0]) != self.selected:
            if self._dirty_form():
                self.status.set('当前行有未加入/更新的修改，请先加入新行或更新选中；也可取消整个列表。')
                if self.selected is not None:
                    self.table.selection_set(str(self.selected))
                else:
                    self.table.selection_remove(*selected)
                return
            self.selected = int(selected[0])
            self._set_form(self.rows[self.selected])

    def _dirty_form(self):
        return any(var.get() != self._clean_form.get(key) for key, var in self.variables.items())

    def _read_row(self):
        row = _read_form(self.fields, self.variables)
        if self.key == 'stages' and not row['name']:
            raise ValueError('阶段名称不能为空。')
        if self.key == 'ready_conditions':
            if not row['port']:
                raise ValueError('请选择监测端口。')
            if row['on_V'] <= row['off_V']:
                raise ValueError('开启阈值须高于关闭阈值。')
        return row

    def add(self):
        try:
            row = self._read_row()
            self.rows.append(row)
            self._refresh()
            self.status.set('已加入行；可继续添加，或保存列表。最终会按时间排序。')
            return True
        except (ValueError, TypeError) as error:
            self.status.set(str(error))
            return False

    def update(self):
        if self.selected is None:
            self.status.set('请先选择要更新的行；新内容用“加入新行”。')
            return False
        try:
            self.rows[self.selected] = self._read_row()
            self._refresh(self.selected)
            self.status.set('选中行已更新；点击保存列表后回到主窗口应用并保存。')
            return True
        except (ValueError, TypeError) as error:
            self.status.set(str(error))
            return False

    def delete(self):
        if self.selected is None:
            self.status.set('请先选择要删除的行。')
            return
        del self.rows[self.selected]
        self._refresh()
        self.status.set('行已从当前草稿删除；取消可放弃本次列表修改。')

    def save(self):
        try:
            self.dialog._current_project()
            if self._dirty_form():
                raise ValueError('编辑栏有未加入或更新的修改，请先点击“加入新行”或“更新选中”。')
            rows = copy.deepcopy(self.rows)
            if self.key == 'voltage_profile' and len(rows) == 1:
                raise ValueError('输入电压时序至少需要两个点；清空列表可恢复单次斜坡。')
            time_key = 'time_s' if self.key == 'voltage_profile' else 'after_s' if self.key == 'stages' else None
            if time_key and rows:
                rows.sort(key=lambda row: row[time_key])
                if rows[0][time_key] != 0:
                    raise ValueError('第一行时间必须为0。')
                for previous, current in zip(rows, rows[1:]):
                    if current[time_key] <= previous[time_key]:
                        raise ValueError('时间必须严格递增，不能重复。')
                    if self.key == 'stages' and previous['after_s']+previous['ramp_s'] > current['after_s']+1e-12:
                        raise ValueError('阶段过渡时间不能越过下一阶段开始时间。')
            if self.key == 'ready_conditions' and len({row['port'] for row in rows}) != len(rows):
                raise ValueError('监测端口不能重复，请更新原有条件。')
            self.dialog.draft[self.group][self.identity][self.key] = rows
            self.dialog.status.set(f'{self.identity} · {LIST_TITLES[self.key]}已存入草稿；请点击“应用并保存”。')
            self.cancel()
            self.owner._show(self.owner.current)
            return True
        except (ValueError, TypeError, KeyError) as error:
            self.status.set('列表未保存：'+str(error))
            return False

    def cancel(self):
        if not self.closed:
            self.closed = True
            if self.sash_job:
                self.win.after_cancel(self.sash_job)
                self.sash_job = None
            self.win.grab_release()
            self.win.destroy()

    def _destroyed(self, event):
        if event.widget is self.win:
            self.closed = True
            if getattr(self, 'sash_job', None):
                self.win.after_cancel(self.sash_job)
                self.sash_job = None


class RecordEditor:
    """A scrollable table and field sheet; switching records keeps local edits."""

    def __init__(self, dialog, title, records, fields, note, *, extra_fields=None):
        self.dialog, self.records, self.fields, self.note = dialog, records, fields, note
        self.extra_fields, self.current_fields = extra_fields or {}, fields
        self.current = None
        self.variables = {}
        # Keep a legal saved value and an explicitly unapplied input draft for
        # inactive protection modes. Switching modes must not silently erase
        # a user's edit or let an invisible field block the active mode.
        self._source_valid = {}
        self._source_text_drafts = {}
        self.page = ttk.Frame(dialog.tabs, padding=8)
        dialog.tabs.add(self.page, text=title)
        panes = ttk.Panedwindow(self.page, orient='vertical')
        panes.pack(fill='both', expand=True)
        self.panes, self._pane_size = panes, None
        panes.bind('<Configure>', self.layout_panes)
        table_box = ttk.Frame(panes, height=145)
        panes.add(table_box, weight=1)
        table_box.columnconfigure(0, weight=1)
        table_box.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table_box, columns=('id', 'name'), show='headings',
                                  height=4, selectmode='browse', style='Sequence.Treeview')
        for name, label, width in (('id', '节点 / 输出 / 连接 ID', 230), ('name', '工程名称 / 连接', 550)):
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=180, stretch=True)
        self.table.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(table_box, orient='vertical', command=self.table.yview)
        sx = ttk.Scrollbar(table_box, orient='horizontal', command=self.table.xview)
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        self.table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.scroll = ScrollableResults(panes)
        panes.add(self.scroll, weight=3)
        for index, (group, identity, name) in enumerate(records):
            self.table.insert('', 'end', iid=str(index), values=(identity, name))
        self.table.bind('<<TreeviewSelect>>', self.select)
        if records:
            self.table.selection_set('0')
            self._show(0)
        else:
            ttk.Label(self.scroll.content, text='当前工程没有此类节点。', style='System.TLabel').pack(anchor='w', padx=10, pady=10)

    def layout_panes(self, _event=None):
        height = self.panes.winfo_height()
        size = int(self.dialog.font_choice.get())
        if height < 100 or self._pane_size == (height, size):
            return
        self._pane_size = (height, size)
        # Always leave an actual record row below the table heading; retain
        # a usable field viewport as well. Users may then move the sash.
        table_height = min(max(110, 2*size+58), height-max(50, size+10))
        self.panes.sashpos(0, table_height)

    def store(self):
        if self.current is not None:
            group, identity, _ = self.records[self.current]
            if group != 'sources':
                self.dialog.draft[group][identity].update(_read_form(self.current_fields, self.variables))
                return
            rules = {'foldback_short_A': ('foldback', 1e-9, 1e9, True),
                     'trip_delay_s': ('hiccup', 1e-6, 10., False),
                     'retry_s': ('hiccup', 1e-6, 10., False)}
            mode = self.variables['protection_mode'].get().split(' · ', 1)[0]
            values = _read_form(tuple(field for field in self.current_fields if field[0] not in rules), self.variables)
            for field in self.current_fields:
                key, label, *_ = field
                if key not in rules:
                    continue
                active, low, high, optional = rules[key]
                cache_key = (identity, key)
                raw = self.variables[key].get()
                try:
                    value = _read_form((field,), self.variables)[key]
                    if not (value is None and optional) and not (value is not None and low <= value <= high):
                        raise ValueError(label+'超出允许范围。')
                except (ValueError, TypeError):
                    if mode == active:
                        raise
                    value = self._source_valid[cache_key]
                    self._source_text_drafts[cache_key] = raw
                else:
                    self._source_valid[cache_key] = value
                    self._source_text_drafts.pop(cache_key, None)
                values[key] = value
            self.dialog.draft[group][identity].update(values)

    def _show(self, index):
        for child in self.scroll.content.winfo_children():
            child.destroy()
        self.current = index
        group, identity, name = self.records[index]
        self.current_fields = self.fields + self.extra_fields.get(identity, ())
        options = ('voltage_profile',) if group == 'sources' else ('ready_conditions',) if group == 'units' else ('stages', 'ready_conditions') if group in ('loads', 'rail_loads') else ()
        tools = ttk.Frame(self.scroll.content)
        tools.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        tools.columnconfigure(0, weight=1)
        self.list_buttons = {}
        for row, key in enumerate(options):
            count = len(self.dialog.draft[group][identity].get(key, []))
            button = ttk.Button(tools, text=f'{LIST_TITLES[key]} · {count} 项 · 编辑…',
                                command=lambda k=key: self.edit_list(k), style='SystemPrimary.TButton')
            button.grid(row=row, column=0, sticky='ew', pady=3)
            self.list_buttons[key] = button
        if group in ('loads', 'rail_loads'):
            text = '分阶段负载已启用：下方固定运行功率/建立时间仅为旧配置备用。' if self.dialog.draft[group][identity].get('stages') else '当前为单一 R/I/P 负载。可添加固件启动、通信投入、运行等阶段。'
            _wrap(ttk.Label(tools, text=text, style='System.TLabel', foreground='#1c5e98',
                           wraplength=650)).grid(row=len(options), column=0, sticky='ew', pady=5)
        if group == 'sources' and self.dialog.draft[group][identity].get('voltage_profile'):
            _wrap(ttk.Label(tools, text='多次上电/掉电列表已启用，单次斜坡设置保留但不生效。',
                           style='System.TLabel', foreground='#1c5e98', wraplength=650)).grid(row=1, column=0, sticky='ew', pady=5)
        form = ttk.Frame(self.scroll.content)
        form.grid(row=1, column=0, sticky='ew')
        _wrap(ttk.Label(self.scroll.content, text=self.note, style='System.TLabel', foreground='#6e581c',
                       wraplength=650, justify='left')).grid(row=2, column=0, sticky='ew', padx=5, pady=7)
        self.scroll.content.columnconfigure(0, weight=1)
        self.variables = _form(form, self.current_fields, self.dialog.draft[group][identity], ports=self.dialog.ports)
        self.form = form
        if group == 'sources':
            for key in ('foldback_short_A', 'trip_delay_s', 'retry_s'):
                cache_key = (identity, key)
                self._source_valid.setdefault(cache_key, self.dialog.draft[group][identity][key])
                if cache_key in self._source_text_drafts:
                    self.variables[key].set(self._source_text_drafts[cache_key])
            self.variables['protection_mode'].trace_add('write', self._source_visibility)
            self._source_visibility()
        from ui_preferences import apply_studio_fonts
        apply_studio_fonts(self.scroll.content, int(self.dialog.font_choice.get()))
        self.scroll.canvas.yview_moveto(0)
        self.scroll.sync()

    def _source_visibility(self, *_args):
        mode = self.variables['protection_mode'].get().split(' · ', 1)[0]
        for key, visible in (('foldback_short_A', mode == 'foldback'),
                             ('trip_delay_s', mode == 'hiccup'), ('retry_s', mode == 'hiccup')):
            widget = self.form.sequence_field_boxes[key]
            widget.grid() if visible else widget.grid_remove()
        self.scroll._schedule_sync()

    def edit_list(self, key):
        try:
            self.dialog._current_project()
            self.store()
            self.list_editor = SequenceListEditor(self, key)
            return self.list_editor
        except (ValueError, TypeError, KeyError) as error:
            self.dialog.status.set('请先核对当前输入：'+str(error))
            return None

    def select(self, _event=None):
        selected = self.table.selection()
        if not selected or int(selected[0]) == self.current:
            return
        try:
            self.store()
        except ValueError as error:
            self.dialog.status.set(str(error))
            if self.current is not None:
                self.table.selection_set(str(self.current))
            return
        self._show(int(selected[0]))


class SystemSequenceDialog:
    def __init__(self, workspace, *, container=None, settings_context=None, navigate=None, on_close=None):
        self.workspace, self.project = workspace, workspace.project
        self.draft = normalize(self.project)
        from system_sequence_config import nominal_ports
        self.ports = tuple(nominal_ports(self.project))
        self.job = self.poll_id = None
        self.mailbox = queue.Queue()
        self.result = {}
        self.terminal_received = False
        self.directory = None
        self.close_pending = False
        self.closed = False
        self.embedded = container is not None
        self.navigate = navigate
        self.on_close = on_close
        self.settings_context = settings_context
        self.win = win = container.winfo_toplevel() if self.embedded else tk.Toplevel(workspace.root)
        if not self.embedded:
            win.title('系统联合启停仿真 · 集中配置与结果')
            win.transient(workspace.root)
            width, height = min(1140, win.winfo_screenwidth()-70), min(850, win.winfo_screenheight()-100)
            win.geometry(f'{width}x{height}')
            win.minsize(min(780, width), min(520, height))
            win.protocol('WM_DELETE_WINDOW', self.close)
        self.status = tk.StringVar(win, '未运行 · 确认设置后，点击「开始启停仿真」。')
        self.output = tk.StringVar(win, str(Path.home()/'系统联合启停仿真'))
        from spice_runtime import find_ltspice
        self.executable = settings_context.executable if settings_context else tk.StringVar(win, find_ltspice() or '')
        body = ttk.Frame(container if self.embedded else win, padding=10)
        self.frame = body
        self.lifecycle = self.frame if self.embedded else self.win
        self.lifecycle.bind('<Destroy>', self._destroyed, add='+')
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        heading = ttk.Frame(body)
        heading.grid(row=0, column=0, sticky='ew', pady=(0, 7))
        ttk.Label(heading, text='系统联合启停仿真', style='System.TLabel').pack(side='left')
        from ui_preferences import font_control, font_size
        self.font_choice = font_control(heading, self.choose_font)
        _wrap(ttk.Label(body, textvariable=self.status, style='ResultConclusion.TLabel', wraplength=1000,
                       justify='left')).grid(row=1, column=0, sticky='ew', pady=(0, 7))
        self.tabs = ttk.Notebook(body)
        self.tabs.grid(row=2, column=0, sticky='nsew')
        self._build_run_page()
        sources = [('sources', row['id'], row['name']) for row in self.project.get('sources', [])]
        units = [('units', row['id'], row['name']) for row in self.project.get('units', [])]
        from ldo import is_ldo
        ldo_fields = {row['id']: LDO_FIELDS for row in self.project.get('units', []) if is_ldo(row['spec'])}
        loads = [('loads', row['id'], '自定义负载 · '+row['name']) for row in self.project.get('loads', [])]
        for unit in self.project.get('units', []):
            for index, rail in enumerate(unit.get('rails', []), 1):
                identity = f"{unit['id']}/OUT{index}"
                if identity in self.draft.get('rail_loads', {}):
                    loads.append(('rail_loads', identity, '额外端口负载 · '+unit['name']))
        edges = [('connections', row['id'], f"{row['source']['id']} → {row['target']}") for row in self.project.get('connections', [])]
        self.editors = [
            RecordEditor(self, '输入源', sources, SOURCE_FIELDS, '源内阻默认 50 mΩ 为工程假设。仅比较模式不影响电流；恒流/折返/打嗝会限制供流，须填写明确门限。主动保护暂不支持源串联电感，需另建续流通路。'),
            RecordEditor(self, '电源启停', units, UNIT_FIELDS, '输入 UVLO 在输入防反后检测；VCC 是理想供电，不能代替输入 UVLO。芯片 Vcs、消隐与打嗝沿用单元控制器配置。LDO 无 EN 引脚时不施加外部 EN。', extra_fields=ldo_fields),
            RecordEditor(self, '负载', loads, LOAD_FIELDS, '有声明下游连接的输出不再自动叠加额定负载。各阶段为总需求，按事件后的相对时间推进；掉压复位，电容继续连接。I/P阶段同样需要正的本地耗功启停门限。'),
            RecordEditor(self, '支路', edges, EDGE_FIELDS, '连接、二极管方式与画布一致。支路内阻默认 10 mΩ 为工程假设，寄生电感须用户声明。'),
        ]
        footer = ttk.Frame(body)
        footer.grid(row=3, column=0, sticky='ew', pady=(9, 0))
        self.apply_button = ttk.Button(footer, text='应用并保存', command=self.apply, style='SystemPrimary.TButton')
        self.run_button = ttk.Button(footer, text='开始启停仿真', command=self.start, style='SystemPrimary.TButton')
        self.cancel_button = ttk.Button(footer, text='取消运行', command=self.cancel, state='disabled', style='System.TButton')
        close_button = ttk.Button(footer, text='关闭', command=self.close, style='System.TButton')
        self.footer, self.action_buttons = footer, (self.apply_button, self.run_button, self.cancel_button, close_button)
        self.action_columns = 0
        footer.bind('<Configure>', self._layout_actions)
        self._apply_fonts(font_size())
        self._layout_actions()

    def _layout_actions(self, _event=None):
        minimum = max(button.winfo_reqwidth() for button in self.action_buttons)+12
        available = self.footer.winfo_width()
        columns = max(1, min(4, available // minimum))
        if columns == 3:
            columns = 2
        if columns == self.action_columns:
            return
        self.action_columns = columns
        for index in range(4):
            self.footer.columnconfigure(index, weight=1 if index < columns else 0)
        for index, button in enumerate(self.action_buttons):
            button.grid(row=index//columns, column=index%columns, sticky='ew', padx=3, pady=3)

    def _build_run_page(self):
        page = ttk.Frame(self.tabs)
        self.tabs.add(page, text='运行与结果')
        self.run_scroll = ScrollableResults(page)
        self.run_scroll.pack(fill='both', expand=True)
        content = self.run_scroll.content
        content.columnconfigure(0, weight=1)
        actions = ttk.Frame(content)
        actions.grid(row=0, column=0, sticky='ew', pady=(4, 6))
        self.open_report = ttk.Button(actions, text='打开报告', command=self.view_report, state='disabled', style='System.TButton')
        self.open_report.pack(side='left', padx=(0, 6))
        self.open_folder = ttk.Button(actions, text='打开运行目录', command=self.view_folder, state='disabled', style='System.TButton')
        self.open_folder.pack(side='left')

        paths = ttk.LabelFrame(content, text='本机运行路径', padding=10)
        paths.grid(row=1, column=0, sticky='ew', pady=5)
        paths.columnconfigure(0, weight=1)
        paths_to_configure = [('结果保存目录', self.output, self.pick_output)]
        if not self.embedded:
            paths_to_configure.append(('LTspice 程序（留空=自动查找）', self.executable, self.pick_executable))
        for row, (label, variable, command) in enumerate(paths_to_configure):
            ttk.Label(paths, text=label, style='System.TLabel').grid(row=row*2, column=0, sticky='w')
            ttk.Entry(paths, textvariable=variable, style='System.TEntry', font=('Microsoft YaHei UI', -14)).grid(row=row*2+1, column=0, sticky='ew', pady=(3, 8))
            ttk.Button(paths, text='选择…', command=command, style='System.TButton').grid(row=row*2+1, column=1, padx=(8, 0))
        if self.embedded:
            ttk.Button(paths,text='设备与模型…',command=lambda:self.navigate('tools'),
                       style='System.TButton').grid(row=2,column=1,sticky='e')
            ttk.Label(paths,textvariable=self.executable,style='System.TLabel').grid(row=2,column=0,sticky='w')
        settings = ttk.LabelFrame(content, text='联合瞬态设置', padding=8)
        settings.grid(row=2, column=0, sticky='ew', pady=6)
        self.setting_variables = _form(settings, SETTINGS, self.draft['settings'])
        scope = ttk.LabelFrame(content, text='模型范围', padding=8)
        scope.grid(row=3, column=0, sticky='ew', pady=6)
        _wrap(ttk.Label(scope, text='各单元用实际开关拓扑与控制器行为模型，VCC 采用理想偏置。缺少 UVLO、软启动、PG 或限流配置时标为未知。'
                       '\n负载和下级电源接在防反后端口。源内阻 50 mΩ、支路内阻 10 mΩ 为默认工程初值。'
                       '源默认阻断回流，使用吸流模式前请核对实物能力。',
                       style='Muted.TLabel', wraplength=950, justify='left')).pack(fill='x')
        ttk.Label(content, text='运行记录', style='System.TLabel').grid(row=4, column=0, sticky='w', pady=5)
        logbox = ttk.Frame(content)
        logbox.grid(row=5, column=0, sticky='ew')
        logbox.columnconfigure(0, weight=1)
        self.log = tk.Text(logbox, height=12, wrap='word', state='disabled', font=('Microsoft YaHei UI', -14))
        self.log.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(logbox, orient='vertical', command=self.log.yview)
        sy.grid(row=0, column=1, sticky='ns')
        self.log.configure(yscrollcommand=sy.set)

    def _apply_fonts(self, size):
        from ui_preferences import apply_studio_fonts
        apply_studio_fonts(self.win, size)
        self.font_choice.set(str(size))
        style = ttk.Style(self.win)
        style.configure('Sequence.Treeview', font=('Microsoft YaHei UI', -size), rowheight=max(30, size+14))
        style.configure('Sequence.Treeview.Heading', font=('Microsoft YaHei UI', -size))
        style.configure('Sequence.TNotebook', font=('Microsoft YaHei UI', -size))
        style.configure('Sequence.TNotebook.Tab', font=('Microsoft YaHei UI', -size), padding=(9, 6))
        self.tabs.configure(style='Sequence.TNotebook')
        for editor in getattr(self, 'editors', []):
            editor._pane_size = None
            self.win.after_idle(editor.layout_panes)
        if hasattr(self, 'footer'):
            self.action_columns = 0
            self.win.after_idle(self._layout_actions)

    def choose_font(self, value):
        from ui_preferences import save_font_size
        size = save_font_size(value)
        self.font_choice.set(str(size))
        self._apply_fonts(size)

    def _current_project(self):
        if self.workspace.project is not self.project:
            raise ValueError('画布已切换工程；请关闭本窗口后从当前工程重新打开联合启停配置。')

    def config_snapshot(self):
        self._current_project()
        for editor in self.editors:
            editor.store()
        candidate = copy.deepcopy(self.draft)
        candidate['settings'].update(_read_form(SETTINGS, self.setting_variables))
        return normalize(self.project, candidate)

    def apply(self):
        try:
            value = self.config_snapshot()
            self.project['sequence_config'] = copy.deepcopy(value)
            self.draft = value
            self.workspace.changed('联合启停配置已保存；未运行电气仿真。保存系统工程可一并导出。')
            labels = {field[0]: field[1] for field in SOURCE_FIELDS}
            notes = [identity+' · '+labels[key] for editor in self.editors
                     for identity, key in editor._source_text_drafts]
            message = '设置已保存 · 可随系统工程导出。'
            if not value['settings']['include_switching_capacitance']:
                message += ' Buck/Boost 沿用单元的寄生电容设置。缺少寄生电容时，DCM 电流归零可能卡顿。'
            if notes:
                message += '\n无效草稿未应用。切回对应保护模式可修正下列字段。\n'+'、'.join(notes)
            self.status.set(message)
            return True
        except (ValueError, TypeError, KeyError) as error:
            self.status.set('保存失败 · ' + str(error))
            return False

    def pick_output(self):
        value = filedialog.askdirectory(parent=self.win, title='选择联合启停结果目录', initialdir=self.output.get() or None)
        if value:
            self.output.set(value)

    def pick_executable(self):
        value = filedialog.askopenfilename(parent=self.win, title='选择 LTspice 程序', filetypes=[('程序', '*.exe'), ('所有文件', '*')])
        if value:
            self.executable.set(value)

    def append(self, value):
        if isinstance(value, dict):
            value = value.get('message') or json.dumps(value, ensure_ascii=False, default=str)
        self.log.configure(state='normal')
        self.log.insert('end', str(value)+'\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self):
        if self.job is not None or not self.apply():
            return
        output = self.output.get().strip()
        if not output:
            self.status.set('未运行 · 请选择结果保存目录。')
            return
        snapshot = copy.deepcopy(self.project)
        executable = self.executable.get().strip() or None
        mailbox = self.mailbox
        stop = self.stop_event = threading.Event()
        self.result, self.directory = {}, None
        self.terminal_received = False
        self.open_report.configure(state='disabled')
        self.open_folder.configure(state='disabled')
        self.run_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.status.set('运行中 · 已固定本次仿真输入。')
        self.append('开始联合启停仿真。当前画布后续编辑不会改变本次冻结输入。')
        self.tabs.select(0)

        def worker():
            try:
                from system_sequence_runtime import run
                result = run(snapshot, output, ltspice=executable, cancelled=stop.is_set,
                             progress=lambda value: mailbox.put(('progress', value)))
                mailbox.put(('done', result))
            except BaseException as error:
                mailbox.put(('error', dict(message=str(error), directory=getattr(error, 'directory', None))))

        self.job = threading.Thread(target=worker, name='system-sequence', daemon=True)
        self.job.start()
        self.poll_id = self.win.after(100, self.poll)

    def poll(self):
        self.poll_id = None
        try:
            while True:
                kind, payload = self.mailbox.get_nowait()
                if kind == 'progress':
                    self.append(payload)
                    message = payload.get('message', payload) if isinstance(payload, dict) else payload
                    state = '正在取消' if self.stop_event.is_set() else '运行中'
                    self.status.set(f'{state} · {message}')
                elif kind == 'done':
                    self.terminal_received = True
                    self.result = payload if isinstance(payload, dict) else {'summary': str(payload)}
                    self.directory = self.result.get('directory') or self.result.get('output_dir')
                    path = self.result.get('report_path') or self.result.get('readme_path') or self.result.get('result_path')
                    if not self.directory and path:
                        self.directory = str(Path(path).parent)
                    status = self.result.get('status', 'unknown')
                    label = {'complete': '已完成 · 报告包含启停时序、电流峰值和限流判定。',
                             'completed': '已完成 · 报告包含启停时序、电流峰值和限流判定。',
                             'cancelled': '已取消 · 可查看已生成的运行记录。', 'failed': '失败 · 请查看运行记录。',
                             'partial': '部分完成 · 请核对未完成或未覆盖项目。'}.get(status, '待复核 · '+str(status))
                    if status in ('complete', 'completed'):
                        observations = _observed_limits(self.result.get('summary'))
                        if observations:
                            label += '\n' + observations
                    if self.result.get('report_error'):
                        if status in ('complete', 'completed'):
                            label = '部分完成 · 仿真已完成，报告导出失败。'
                        label += '\n' + str(self.result['report_error'])
                    self.status.set(label)
                    self.append(label)
                    if isinstance(self.result.get('summary'), str) and self.result['summary']:
                        self.append(self.result['summary'])
                    if self.result.get('result_path'):
                        self.append('结果数据 · ' + str(self.result['result_path']))
                    self.open_report.configure(state='normal' if path and Path(path).is_file() else 'disabled')
                elif kind == 'error':
                    self.terminal_received = True
                    self.directory = payload.get('directory')
                    self.status.set('失败 · ' + payload['message'])
                    self.append(self.status.get())
        except queue.Empty:
            pass
        # The worker enqueues its terminal event immediately before returning.
        # Keep ownership until it has actually left, including cancellation.
        if self.job is not None and self.job.is_alive():
            self.poll_id = self.win.after(100, self.poll)
            return
        if not self.mailbox.empty():
            self.poll_id = self.win.after(0, self.poll)
            return
        if self.job is not None:
            if not self.terminal_received and self.mailbox.empty():
                self.status.set('失败 · 未取得有效结果，请查看运行记录。')
            self.job.join(timeout=0)
            self.job = None
        self.run_button.configure(state='normal')
        self.cancel_button.configure(state='disabled')
        self.open_folder.configure(state='normal' if self.directory and Path(self.directory).is_dir() else 'disabled')
        if self.close_pending:
            self._destroy()

    def cancel(self):
        if self.job is not None:
            self.stop_event.set()
            self.cancel_button.configure(state='disabled')
            self.status.set('正在取消 · 等待 LTspice 停止。')

    def view_report(self):
        path = self.result.get('report_path') or self.result.get('readme_path') or self.result.get('result_path')
        if path and Path(path).is_file():
            self._open(path)

    def view_folder(self):
        if self.directory and Path(self.directory).is_dir():
            self._open(self.directory)

    def _open(self, path):
        try:
            os.startfile(str(path))
        except OSError as error:
            self.status.set('未能打开路径：' + str(error))

    def close(self):
        if self.job is not None:
            self.close_pending = True
            self.cancel()
            return
        self._destroy()

    def _destroy(self):
        if self.closed:
            return
        self.closed = True
        if self.poll_id:
            self.win.after_cancel(self.poll_id)
            self.poll_id = None
        if self.on_close is not None:
            self.on_close()
        else:
            self.lifecycle.destroy()

    def _destroyed(self, event):
        if event.widget is self.lifecycle:
            self.closed = True
            if self.job is not None:
                self.stop_event.set()
            if self.poll_id:
                try:
                    self.win.after_cancel(self.poll_id)
                except tk.TclError:
                    pass
                self.poll_id = None


def show(workspace):
    dialog = getattr(workspace, '_sequence_dialog', None)
    if dialog and not dialog.closed and dialog.win.winfo_exists():
        dialog.win.deiconify()
        dialog.win.lift()
        return dialog.win
    dialog = workspace._sequence_dialog = SystemSequenceDialog(workspace)
    return dialog.win
