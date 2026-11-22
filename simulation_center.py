"""One non-modal simulation workspace per open design or power tree."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from scrollable_results import ScrollableResults
from simulation_environment_ui import EnvironmentPanel


ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')


class SimulationCenter:
    def __init__(self, owner, *, system=False):
        self.owner = owner
        self.system = system
        self.scope = owner.project if system else None
        self.pages = {}
        self.panels = {}
        self.circuit_key = None
        self.closed = False
        self.close_pending = False
        self.pending_close = None
        self.loaded_design = getattr(owner, '_design_load_revision', 0)
        self.window = win = tk.Toplevel(owner.root)
        win.title('仿真配置中心')
        win.transient(owner.root)
        width = min(1580, win.winfo_screenwidth() - 60)
        height = min(920, win.winfo_screenheight() - 100)
        win.geometry(f'{width}x{height}')
        win.minsize(min(960, width), min(610, height))
        tab_style = 'SimulationCenter.TNotebook'
        ttk.Style(win).configure(tab_style+'.Tab', font=('Microsoft YaHei UI', -15),
                                 padding=(12,7))
        win.protocol('WM_DELETE_WINDOW', self.close)
        win.bind('<Destroy>', self.destroyed, add='+')

        outer = ttk.Frame(win, padding=(10, 7))
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='仿真配置中心', font=('Microsoft YaHei UI', -18, 'bold')).pack(anchor='w', pady=(0, 8))
        self.note = ttk.Label(outer, style='ResultConclusion.TLabel', wraplength=900, justify='left')
        self.tabs = ttk.Notebook(outer, style=tab_style)
        self.tabs.pack(fill='both', expand=True)
        self.tabs.bind('<<NotebookTabChanged>>', self.refresh_page)

        config = {} if system else owner._config_dict()
        if system:
            self._add_tab('sequence', '系统启停')
            self._add_tab('unit', '单元仿真')
        else:
            self._add_tab('circuit', '电路仿真')
            self._add_tab('field', '变压器电磁')
            self._add_tab('joint', '联合仿真')
        utilities = ScrollableResults(self._add_tab('tools', '设备与模型'))
        utilities.pack(fill='both', expand=True)
        self.environment = EnvironmentPanel(utilities.content, config,
            field_enabled=not system and _topology(config) in ISOLATED)
        self.environment.pack(fill='x', expand=True)

    def _add_tab(self, key, label):
        page = ttk.Frame(self.tabs)
        self.pages[key] = page
        self.tabs.add(page, text=label)
        return page

    def go(self, target, *, comparison=False):
        self.tabs.select(self.pages[target])
        panel = self._ensure(target)
        if target == 'circuit' and comparison and panel is not None:
            panel.edit_group('测试与对比报告')
        self.window.deiconify()
        self.window.lift()
        return self.window

    def refresh_page(self, _event=None):
        selected = self.tabs.select()
        key = next((key for key,page in self.pages.items() if str(page) == selected), None)
        if key is not None:
            try:
                self._ensure(key)
            except (ValueError, OSError, tk.TclError) as exc:
                self._show_note('待复核 · ' + str(exc))

    def _show_note(self, text):
        if text:
            self.note.configure(text=text, wraplength=max(320, self.window.winfo_width()-35))
            self.note.pack(fill='x', before=self.tabs, pady=(0, 7))
        else:
            self.note.pack_forget()

    def _replace_with_note(self, key, text):
        for widget in self.pages[key].winfo_children():
            widget.destroy()
        ttk.Label(self.pages[key], text=text, style='ResultConclusion.TLabel', wraplength=640,
                  justify='left').pack(fill='x', padx=20, pady=18)

    def _clear_unit_panels(self):
        for panel in self.panels.values():
            panel.frame.destroy()
        self.panels.clear()

    def _ensure(self, key):
        if self.closed or self.close_pending:
            return None
        self._show_note('')
        if self.system:
            return self._ensure_system(key)
        config = self.owner._config_dict()
        revision = getattr(self.owner, '_design_load_revision', 0)
        if revision != self.loaded_design:
            if self.running():
                self._show_note('运行中 · 任务结束后可按新工程配置。')
                return None
            self._clear_unit_panels()
            self.loaded_design = revision
        topology = _topology(config)
        field_enabled = topology in ISOLATED
        if self.environment.field_enabled != field_enabled:
            if self.running():
                self._show_note('运行中 · 任务结束后可按新拓扑配置。')
                return None
            container = self.environment.master
            ltspice = self.environment.executable.get()
            self._clear_unit_panels()
            self.environment.destroy()
            self.environment = EnvironmentPanel(container, config, field_enabled=field_enabled)
            self.environment.executable.set(ltspice)
            self.environment.pack(fill='x', expand=True)
        self.environment.set_config(config)
        if key == 'circuit':
            return self._ensure_circuit()
        if key not in ('field', 'joint'):
            return None
        existing = self.panels.get(key)
        from spice_ui import supports_design
        if not field_enabled or (key == 'joint' and not supports_design(self._parameters())):
            if existing and existing.job is not None:
                return existing
            self.panels.pop(key, None)
            if topology == 'LLC':
                reason = '暂未接入 · LLC 当前支持电路仿真。'
            elif not field_enabled:
                reason = '不适用 · 当前拓扑没有可提取的变压器。'
            else:
                reason = '暂未接入 · 当前控制模式可单独运行变压器电磁仿真。'
            self._replace_with_note(key, reason)
            return None
        if existing:
            if existing.job is None:
                refresh = existing.refresh_preflight if key == 'field' else existing.set_config
                refresh(config)
            return existing
        for widget in self.pages[key].winfo_children():
            widget.destroy()
        options = dict(container=self.pages[key], settings_context=self.environment, navigate=self.go)
        if key == 'field':
            from transformer_sim_ui import _SimulationDialog
            panel = _SimulationDialog(self.owner, config, **options)
            self.owner._transformer_simulation_dialog = panel
        else:
            from joint_simulation_ui import JointSimulationDialog
            panel = JointSimulationDialog(self.owner, config, **options)
            self.owner._joint_simulation_dialog = panel
        self.panels[key] = panel
        return panel

    def _parameters(self):
        parameters = self.owner.get_params(check_curve_sources=False)
        parameters.update(self.owner._rcd_parameters())
        return parameters

    def _ensure_circuit(self):
        from cot_settings import active as cot_active
        from spice_ui import open_export_dialog, supports_design

        parameters = self._parameters()
        identity = (parameters.get('topology'), parameters.get('feedback_mode'),
                    parameters.get('control_mode'),
                    parameters.get('llc_bridge') if parameters.get('topology') == 'LLC' else None,
                    cot_active(parameters), id(self.environment))
        existing = self.panels.get('circuit')
        if existing and (identity == self.circuit_key or existing.busy()):
            return existing
        self.panels.pop('circuit', None)
        for widget in self.pages['circuit'].winfo_children():
            widget.destroy()
        self.circuit_key = identity
        if not supports_design(parameters):
            self._replace_with_note('circuit', '暂未接入 · 当前拓扑或反馈模式暂无 LTspice 闭环对比。')
            return None

        def apply(data):
            self.owner._spice_config = dict(data)
            self.owner.schedule_update()
            self.owner.status_var.set('电路仿真配置已应用，可随设计工程保存。')

        panel = open_export_dialog(self.owner.root, parameters, apply, get_parameters=self._parameters,
            container=self.pages['circuit'], settings_context=self.environment, navigate=self.go)
        self.panels['circuit'] = panel
        return panel

    def _ensure_system(self, key):
        if key == 'sequence':
            if key not in self.panels:
                from system_sequence_ui import SystemSequenceDialog
                panel = SystemSequenceDialog(self.owner, container=self.pages[key],
                    settings_context=self.environment, navigate=self.go, on_close=self.close)
                self.owner._sequence_dialog = panel
                self.panels[key] = panel
            return self.panels[key]
        if key == 'unit' and not self.pages[key].winfo_children():
            page = self.pages[key]
            units = self.scope.get('units', [])
            names = {f"{row['id']} · {row['name']}": row['id'] for row in units}
            ttk.Label(page, text='选择电源单元后，可打开该单元的仿真配置。' if names else
                      '暂无电源单元 · 请先在系统架构中添加电源单元。',
                      style='ResultConclusion.TLabel', wraplength=650).pack(fill='x', padx=18, pady=(18, 9))
            selected = tk.StringVar(page, next(iter(names), ''))
            ttk.Combobox(page, textvariable=selected, state='readonly', values=list(names),
                         width=30).pack(anchor='nw', padx=18, pady=8)

            def open_unit():
                identity = names.get(selected.get())
                if identity is None:
                    return
                calculator = self.owner.open_unit(identity)
                if calculator is None:
                    return
                self.owner._system_simulation_return = self._restore_window
                self.window.withdraw()
                if hasattr(calculator, '_open_simulation_center'):
                    calculator._open_simulation_center()
            ttk.Button(page, text='打开单元仿真配置', command=open_unit,
                       state='normal' if names else 'disabled').pack(anchor='nw', padx=18)
        return None

    def _restore_window(self):
        if not self.closed:
            self.window.deiconify()
            self.window.lift()

    def running(self):
        return any(panel.busy() if key == 'circuit' else panel.job is not None
                   for key,panel in self.panels.items())

    def close(self):
        if self.closed:
            return
        if self.running():
            if not self.close_pending:
                self.close_pending = True
                for panel in self.panels.values():
                    panel.cancel()
            self._show_note('正在取消 · 等待求解器停止。')
            self.pending_close = self.window.after(120, self.close)
            return
        self.window.destroy()

    def destroyed(self, event):
        if event.widget is self.window:
            self.closed = True
            if self.pending_close is not None:
                self.window.after_cancel(self.pending_close)


def _topology(config):
    value = config.get('topology')
    return value.get('v') if isinstance(value, dict) else value


def show(owner, tab, *, system=False, comparison=False):
    center = getattr(owner, '_simulation_center', None)
    if center and not center.closed and system and center.scope is not owner.project:
        if center.running():
            messagebox.showinfo('仿真配置中心', '旧工程仍有仿真任务，请先停止。', parent=center.window)
            return center.window
        center.close()
    if not center or center.closed:
        center = owner._simulation_center = SimulationCenter(owner, system=system)
    try:
        return center.go(tab, comparison=comparison)
    except (ValueError, OSError, tk.TclError) as exc:
        center._show_note('待复核 · ' + str(exc))
        center.window.deiconify()
        center.window.lift()
        return center.window
