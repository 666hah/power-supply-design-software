"""Parameter presentation only: the engine's variables and JSON keys stay intact."""
import math
import re
import tkinter as tk
from tkinter import ttk

import magnetics as mag
from capacitor_banks import FIELDS as CAPACITOR_FIELDS
from engineering_ui import Tooltip
from parameter_layout import GROUPS, META, SECTION_ORDER, SECTION_TITLES, applicable, visible
from device_curve_ui import DeviceCurveUI
from diode_curves import DEPRECATED_RD
from custom_core_ui import CustomCoreUI, CoreGeometryEditor
from custom_cores import CUSTOM_CORE, is_custom
from numeric_input import limit_numeric_input


ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
OPTIONAL = {'C_out2': 'cout2_enable', 'Cin2': 'cin2_enable',
            'Vf_din': 'd_in_enable', 'Vf_dout': 'd_out_enable'}
OPTION_NAMES = {'cout2_enable': '启用输出第二电容', 'cin2_enable': '启用输入第二电容',
                'd_in_enable': '启用输入防反二极管', 'd_out_enable': '启用输出防反二极管'}
OUTPUT_OWNED = {'V_out', 'P_out', 'C_out', 'Rc', 'ESL', 'C_out2', 'Rc2', 'ESL2',
                'Vf_diode', 'Rd_diode', 'Qrr', 'Vf_dout', 'Rd_dout', 'ripple_target',
                'Ns', 'd_wire_s', 'n_strand_s','parallel_wires_s'}
PSR_COMPATIBILITY = {'KP', 'fz1', 'fz2', 'fp1', 'fp2'}
LLC_BRIDGE_LABELS = {'half': '半桥 · 2 只主 MOS', 'full': '全桥 · 4 只主 MOS'}
INTEGER_PARAMETERS = {'Np', 'Ns', 'n_strand_p', 'n_strand_s', 'parallel_wires_p',
                      'parallel_wires_s', 'llc_lr_turns', 'llc_lr_strands'}


def display_number(value):
    return f'{value:.10g}'


def search_matches(query, text):
    if not query:
        return True
    normalized = (text+' '+text.replace('µ', 'u')).lower()
    if re.fullmatch(r'[a-z0-9_]+', query):
        return re.search(r'(?<![a-z0-9])'+re.escape(query), normalized) is not None
    return query in normalized


class ParameterPanelUI(DeviceCurveUI, CustomCoreUI):
    def _param_unit_choices(self, key):
        unit = META[key].unit
        options = self.unit_opts.get(key, [])
        return {prefix.replace('u', 'µ') + unit: prefix for prefix in options} if options else {unit: ''}

    def _presentation_context(self):
        topo, mode = self._topo_key(), self._ctrl_key()
        if topo == 'FLYBACK' and self.feedback_mode.get() == 'PSR-MP6005':
            mode = 'Peak Current Mode'
        return topo, mode

    def _llc_winding_ratio(self):
        if self._topo_key() != 'LLC':
            return None
        try:
            primary, secondary = (self.params[key].get() for key in ('Np', 'Ns'))
        except (tk.TclError, ValueError):
            return None
        if all(math.isfinite(value) and value > 0 for value in (primary, secondary)):
            return primary / secondary
        return None

    def _sync_param_field(self, key, *_):
        if key in self._param_binding_busy:
            return
        self._param_binding_busy.add(key)
        try:
            spec = META[key]
            ratio = self._llc_winding_ratio() if key == 'N' else None
            if key == 'N':
                self._param_widgets[key][0].configure(text=(
                    '原副边匝比 Np/Ns（由匝数派生）' if ratio is not None else
                    '原副边匝比 Np/Ns(OUT1) *' if self._multiple_active() else '原副边匝比 Np/Ns *'))
                self._param_widgets[key][1].configure(state='readonly' if ratio is not None else 'normal')
            try:
                value = ratio if ratio is not None else self.params[key].get()
            except (tk.TclError, ValueError):
                # Invalid/incomplete edits remain invalid in the engine variable.
                if self._psr_active() and key in ('f_sw', 'A_sense'):
                    value = 0  # draw the fixed effective value, never the invalid SSR draft
                else:
                    return
            if key in self._param_auto_vars:
                automatic = value == 0
                self._param_auto_vars[key].set(automatic)
                if not automatic and math.isfinite(value):
                    self._param_auto_saved[key] = (value, self.params[key+'_unit'].get())
                self._param_widgets[key][1].configure(state='readonly' if automatic else 'normal')
            text = '自动' if spec.auto and value == 0 else display_number(value * spec.display_factor)
            self._param_display_vars[key].set(text)
            if key in self._param_unit_vars:
                prefix = self.params[key+'_unit'].get()
                full = next((label for label, p in self._param_unit_choices(key).items() if p == prefix), None)
                if full is not None:
                    self._param_unit_vars[key].set(full)
            if key == 'A_sense' and self._psr_active():
                self._param_display_vars[key].set('11')
                self._param_widgets[key][1].configure(state='readonly')
            elif key == 'A_sense':
                self._param_widgets[key][1].configure(state='normal')
            if key == 'f_sw':
                if self._psr_active():
                    prefix = self.params[key+'_unit'].get()
                    self._param_display_vars[key].set(display_number(250e3 / self.units[prefix]))
                self._param_widgets[key][1].configure(state='readonly' if self._psr_active() else 'normal')
                self._param_widgets[key][2].configure(state='disabled' if self._psr_active() else 'readonly')
        finally:
            self._param_binding_busy.discard(key)

    def _param_edit(self, key, *_):
        if key in self._param_binding_busy:
            return
        raw_text = self._param_display_vars[key].get().strip()
        if key in self._param_auto_vars and self._param_auto_vars[key].get():
            return
        try:
            value = float(raw_text) / META[key].display_factor
        except ValueError:
            value = raw_text
        # Prevent canonical-to-view syncing from rewriting a partial edit such
        # as '1.' or silently turning an invalid field into its previous value.
        self._param_binding_busy.add(key)
        try:
            self.params[key].set(value)
            if key in self._param_auto_saved and isinstance(value, float) and value != 0:
                self._param_auto_saved[key] = (value, self.params[key+'_unit'].get())
        finally:
            self._param_binding_busy.discard(key)
        if META[key].auto and key in INTEGER_PARAMETERS and value == 0:
            self._sync_param_field(key)
        self._refresh_param_summaries()

    def _commit_auto_zero(self, key):
        try:
            value = self.params[key].get()
        except (tk.TclError, ValueError):
            return
        if value == 0:
            self._sync_param_field(key)

    def _change_param_unit(self, key):
        choices = self._param_unit_choices(key)
        requested = choices.get(self._param_unit_vars[key].get())
        current = self.params[key+'_unit'].get()
        if requested is None or requested == current:
            return
        try:
            value = self.params[key].get()
        except (tk.TclError, ValueError):
            self._sync_param_field(key)
            self._param_unit_vars[key].set(next((label for label, p in choices.items() if p == current), ''))
            return
        was_building = self._building
        self._building = True
        self._param_binding_busy.add(key)
        try:
            si_value = value * self.units[current]
            self.params[key].set(si_value / self.units[requested])
            self.params[key+'_unit'].set(requested)
        finally:
            self._param_binding_busy.discard(key)
            self._building = was_building
        self._sync_param_field(key)
        self._refresh_param_summaries()
        if not was_building:
            self.schedule_update()

    def _toggle_param_auto(self, key):
        automatic = self._param_auto_vars[key].get()
        was_building = self._building
        self._building = True
        try:
            if automatic:
                try:
                    value = self.params[key].get()
                    if value != 0:
                        self._param_auto_saved[key] = (value, self.params[key+'_unit'].get())
                except (ValueError, tk.TclError):
                    pass
                self.params[key].set(0)
            else:
                saved = self._param_auto_saved.get(key)
                if saved:
                    value, prefix = saved
                    self.params[key].set(value)
                    self.params[key+'_unit'].set(prefix)
                else:
                    self.params[key].set('')
                    self._param_display_vars[key].set('')
                    self._param_widgets[key][1].configure(state='normal')
        finally:
            self._building = was_building
        self._sync_param_field(key)
        self._refresh_param_summaries()
        if not was_building:
            self.schedule_update()

    def _psr_active(self):
        return self._topo_key() == 'FLYBACK' and self.feedback_mode.get() == 'PSR-MP6005'

    def _multiple_active(self):
        return self._topo_key() in ISOLATED and self.multi_enabled.get()

    def _purchased_inductor(self):
        from inductor_selection import TOPOLOGIES
        return self._topo_key() in TOPOLOGIES and not self.params['inductor_design_enabled'].get()

    def _output_owns_parameter(self, key):
        return self._multiple_active() and (key in OUTPUT_OWNED or (key == 'L' and self._topo_key() == 'ACF-FORWARD'))

    def _scalar_parameter_active(self, key):
        """Calculation ownership, independent of search/folding/basic mode."""
        if key in DEPRECATED_RD:return False
        from inductor_selection import DESIGN_FIELDS, FIELDS
        if self._purchased_inductor() and key in DESIGN_FIELDS:return False
        if not self._purchased_inductor() and key in FIELDS:return False
        if key == 'MLT':return False
        if key == 'N' and self._llc_winding_ratio() is not None:
            return False
        topo, mode = self._presentation_context()
        spec = META[key]
        if key == 'gfs' and self._mos_resolved_mode() != 'gfs':return False
        if key == 'mos_curve_vds' and not (self._mos_resolved_mode()=='curve' and self._mos_miller_curve.get('kind')=='output_family'):return False
        if self._mos_charge_parameter_hidden(key):return False
        if key == 'Vgp_off' and self._mos_current_plateau_active():
            return False
        if not applicable(key, topo, mode) or self._output_owns_parameter(key):
            return False
        if spec.enabled_by and not self.params[spec.enabled_by].get():
            return False
        if self._psr_active() and key in PSR_COMPATIBILITY | {'f_sw', 'A_sense'}:
            return False
        return True

    def _build_param_panel(self, parent, specifications, topology_labels, control_labels):
        self.params['mos_miller_mode']=tk.StringVar(value='auto')
        self._mos_miller_curve={}
        self.params['mos_charge_mode']=tk.StringVar(value='manual')
        self._mos_charge_curve={}
        self._diode_curves={}
        self._device_curve_settings={}
        self._curve_binding_busy=False
        self._param_display_vars, self._param_unit_vars = {}, {}
        self._param_auto_vars, self._param_auto_saved = {}, {}
        self._param_binding_busy = set()
        self._param_summary_vars, self._param_subgroups = {}, []
        self._param_extras, self._param_switches, self._param_status_vars = [], {}, {}
        self._param_group_keys = {}
        self._param_search_terms = {}
        self._cap_editors={}
        self._cap_bank_active={'input':False,'output':False}
        self._build_param_filters(self._param_filter_host)
        by_key = {key: (label, units) for key, label, units, _section in specifications}
        # Optional switches must exist before any summaries or filters run.
        from power_stage import DEFAULT_PARAMS
        for key in OPTION_NAMES:
            self.params[key] = tk.BooleanVar(value=DEFAULT_PARAMS.get(key, False))
        rows = {}
        for section in SECTION_ORDER:
            frame = self._add_section(parent, SECTION_TITLES[section])
            self._param_sections[section] = frame
            self._param_group_keys[section] = []
            summary = tk.StringVar()
            self._param_summary_vars[section] = summary
            label = ttk.Label(frame._section_container, textvariable=summary, style='Muted.TLabel',
                              wraplength=350, padding=(9, 4, 9, 7), justify='left')
            label.pack(fill='x', before=frame)
            frame._section_summary = label
            row = 0
            if section == 'spec':
                row = self._build_scheme_rows(frame, row, topology_labels, control_labels)
            if section == 'curves':
                row = self._build_device_curve_controls(frame, row)
            if section == 'mag':
                row = self._build_core_picker_rows(frame, row)
            if section == 'ctrl':
                row = self._build_feedback_rows(frame, row)
            if section == 'device':
                row = self._build_manual_events(frame, row)
            for title, keys in GROUPS[section]:
                group_label = ttk.Label(frame, text=title, style='WorkspaceGroup.TLabel', padding=(6, 4))
                group_label.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(6, 2))
                self._param_subgroups.append((frame, group_label, keys))
                row += 1
                for key in keys:
                    if key in OPTIONAL:
                        switch_key = OPTIONAL[key]
                        check = ttk.Checkbutton(frame, text=OPTION_NAMES[switch_key], variable=self.params[switch_key])
                        check.grid(row=row, column=0, columnspan=4, sticky='w', pady=(4, 2))
                        self._param_switches[switch_key] = check
                        self._register_param_extra(frame, [check], keys, OPTION_NAMES[switch_key]+' '+switch_key)
                        row += 1
                        status = tk.StringVar()
                        status_label = ttk.Label(frame, textvariable=status, style='Muted.TLabel', wraplength=340)
                        status_label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, 3))
                        self._param_status_vars[switch_key] = status
                        self._register_param_extra(frame, [status_label], keys, OPTION_NAMES[switch_key]+' '+switch_key)
                        row += 1
                    label_text, units = by_key[key]
                    self._param_search_terms[key] = title
                    self._param_row(frame, row, key, label_text, units)
                    self._param_group_keys[section].append(key)
                    row += 1
                if title.startswith('Q1 ·'):
                    row = self._build_device_curve_data_button(frame, row, 'Q1 曲线数据…', 'mos')
                elif title.startswith('D1 ·'):
                    row = self._build_device_curve_data_button(frame, row, '整流与续流曲线数据…', 'rectifier')
                elif 'Vf_din' in keys:
                    row = self._build_device_curve_data_button(frame, row, '输入防反曲线数据…', 'input')
                elif 'Vf_dout' in keys:
                    row = self._build_device_curve_data_button(frame, row, '输出防反曲线数据…', 'output')
            if section == 'capacitors':
                from capacitor_ui import BankEditor
                from capacitor_banks import bank
                for side,label in (('input','输入并联电容组'),('output','输出并联电容组')):
                    holder=ttk.LabelFrame(frame,text=label)
                    holder.grid(row=row,column=0,columnspan=4,sticky='ew',pady=5)
                    editor=BankEditor(holder,bank(DEFAULT_PARAMS,side),lambda s=side:self._capacitor_bank_changed(s),
                                      rail=None if side=='input' else 0)
                    editor.pack(fill='x',padx=3,pady=3);self._cap_editors[side]=editor
                    self._register_param_extra(frame,[holder],text=label+' C ESR ESL 电容数量 阻抗曲线 热阻 capacitors',
                        predicate=(lambda:self._multiple_active()==False) if side=='output' else None)
                    row+=1
            if section == 'stage':
                row = self._build_clamp_parameter_rows(frame, row)
                from parasitic_ui import open_editor
                button=ttk.Button(frame,text='设置寄生参数与吸收…',command=lambda:open_editor(self))
                button.grid(row=row,column=0,columnspan=4,sticky='ew',pady=6)
                self._register_param_extra(frame,[button],('N',),'寄生 振铃 Coss Cj 布线 电容 吸收 RC',
                                           predicate=lambda:self._topo_key() != 'LLC')
                row+=1
            if section == 'device':
                self.mos_gate_readout = tk.StringVar(value='MOS 米勒平台电压待计算')
                note = ttk.Label(frame, text='曲线模型仍需填写 Rds(on)、Coss、Vth、内部栅阻和驱动参数。',
                                 style='Muted.TLabel', wraplength=350, justify='left')
                reading = ttk.Label(frame, textvariable=self.mos_gate_readout, style='Muted.TLabel', wraplength=350, justify='left')
                reading.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
                note.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=4)
                self._register_param_extra(frame, [note, reading], ('gfs','Vgp_on','Vgp_off'),
                    'MOS 米勒平台 实际开通关断电流 Id Vgp 曲线 Qgs', predicate=lambda:self._topo_key() != 'LLC')
                row += 2
            row = self._build_output_parameter_rows(frame, row, section)
            if section == 'mag':
                self.transformer_gap_readout = tk.StringVar(value='气隙结果见磁件页。μr 为 0 时采用材料手册值，有效磁路长度 le 由 Ve/Ae 得出。')
                gap_readout = ttk.Label(frame, textvariable=self.transformer_gap_readout,
                                        style='Muted.TLabel', wraplength=350, justify='left')
                gap_readout.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
                self._register_param_extra(frame, [gap_readout], ('mu_r',), '相对磁导率 有效磁路长度 气隙')
                row += 1
                note = ttk.Label(frame, text='磁芯损耗密度 Pv / mW/cm³ = k × (f/kHz)^α × (B/T)^β。\n0 表示自动取值。',
                                 style='Muted.TLabel', wraplength=350, justify='left')
                note.grid(row=row, column=0, columnspan=4, sticky='w', pady=4)
                self._register_param_extra(frame, [note], ('k_core', 'a_core', 'b_core'), '磁损系数 计算约定',
                                           predicate=lambda:not self._purchased_inductor())
                row += 1
            rows[section] = row
        self._param_scheme_row = rows
        # Start with every applicable group expanded. Users can still fold
        # groups explicitly; filtering must never conceal a material model.
        for key in OPTION_NAMES:
            self.params[key].trace_add('write', lambda *_: self._filter_params())
        self.params['inductor_design_enabled'].trace_add('write', lambda *_: self._parameter_context_changed())
        self.params['gfs'].trace_add('write', lambda *_: self._filter_params())
        for key in ('Np', 'Ns'):
            self.params[key].trace_add('write', lambda *_: self._sync_param_field('N'))
        self.params['mos_miller_mode'].trace_add('write', self._mos_mode_changed)
        self.params['mos_charge_mode'].trace_add('write', self._mos_mode_changed)
        for variable in (self.multi_enabled, self.feedback_mode, self.feedback_output):
            variable.trace_add('write', lambda *_: self._parameter_context_changed())
        self._refresh_param_rows()

    def _param_row(self, parent, row, key, original_label, units):
        spec = META[key]
        label = spec.label + (' '+spec.symbol if spec.symbol else '')
        if spec.required:
            label += ' *'
        lab = ttk.Label(parent, text=label, style='Param.TLabel', wraplength=170, justify='left')
        lab.grid(row=row, column=0, sticky='w', padx=(3, 9), pady=3)
        self.param_labels.append(lab)
        parent.columnconfigure(0, weight=1)
        display = tk.StringVar()
        self._param_display_vars[key] = display
        if key == 'buck_phases':
            entry = ttk.Combobox(parent, textvariable=display, values=tuple(range(1, 17)),
                                 state='readonly', width=8)
        else:
            entry = ttk.Entry(parent, textvariable=display, width=8)
            limit_numeric_input(entry, integer=key in INTEGER_PARAMETERS)
            if spec.auto and key not in INTEGER_PARAMETERS:
                # Keep the leading zero of a fractional wire diameter editable.
                for event in ('<FocusOut>', '<Return>'):
                    entry.bind(event, lambda _event, k=key: self._commit_auto_zero(k), add='+')
        entry.grid(row=row, column=1, sticky='ew', padx=(0, 6), pady=3)
        widgets = [lab, entry]
        shown = tk.StringVar()
        self._param_unit_vars[key] = shown
        if len(units) > 1:
            combo = ttk.Combobox(parent, textvariable=shown, values=list(self._param_unit_choices(key)), width=7, state='readonly')
            combo.grid(row=row, column=2, sticky='ew', padx=(0, 5), pady=3)
            combo.bind('<<ComboboxSelected>>', lambda _event, k=key: self._change_param_unit(k))
            widgets.append(combo)
        else:
            unit_label = ttk.Label(parent, textvariable=shown, style='Muted.TLabel', wraplength=78, justify='left')
            unit_label.grid(row=row, column=2, sticky='w', padx=(4, 5))
            widgets.append(unit_label)
        density = key in ('d_wire_p', 'n_strand_p', 'd_wire_s', 'n_strand_s','parallel_wires_p','parallel_wires_s')
        side = ttk.Frame(parent) if density else parent
        if density:
            side.grid(row=row, column=3, sticky='w', padx=(3, 0), pady=3)
            widgets.append(side)
        if spec.auto:
            automatic = tk.BooleanVar(value=self.params[key].get() == 0)
            self._param_auto_vars[key] = automatic
            check = ttk.Checkbutton(side, text='自动', variable=automatic, command=lambda k=key: self._toggle_param_auto(k))
            if density:
                check.pack(anchor='w')
            else:
                check.grid(row=row, column=3, sticky='w', padx=(1, 0))
                widgets.append(check)
        if density:
            self._transformer_density_label(side, 'P' if key.endswith('_p') else 'OUT1').pack(anchor='w')
        self._param_widgets[key] = widgets
        self.params[key].trace_add('write', lambda *_, k=key: self._sync_param_field(k))
        self.params[key+'_unit'].trace_add('write', lambda *_, k=key: self._sync_param_field(k))
        display.trace_add('write', lambda *_, k=key: self._param_edit(k))
        note = original_label+'\n配置字段：'+key+'；内部前缀保持旧格式。'
        if spec.required:
            note += '\n* 当前计算模型所需，请核对规格书和工况；预设不是厂家保证值。'
        if spec.display_factor == 100:
            note += '\n显示为百分数；计算/JSON仍保存0~1比例，不更改计算模型。'
        if spec.auto:
            note += '\n自动切换保留当前手动值；加载新配置后不继承上个设计的手动缓存。'
        if key == 'Rth_transformer':
            note += '\nΔT=(全部绕组铜损+磁芯损耗)×Ri-a；默认100 K/W仅为初始假设，请按实测或热设计填写。不是局部热点热阻。'
        Tooltip(lab, note)
        Tooltip(entry, note)
        self._sync_param_field(key)

    def _resize_parameter_fields(self, content_width):
        signature = (content_width, self._font_k)
        label_widths = {}
        for frame in self._param_sections.values():
            if not frame.winfo_manager() or signature == getattr(frame, '_parameter_wrap_signature', None):
                continue
            frame._parameter_wrap_signature = signature
            columns = [0, 0, 0, 0]
            for child in frame.grid_slaves():
                info = child.grid_info()
                col = int(info.get('column', 0))
                if 0 < col < len(columns) and int(info.get('columnspan', 1)) == 1:
                    columns[col] = max(columns[col], child.winfo_reqwidth() + 10)
            label_widths[frame] = max(55, content_width - 28 - sum(columns[1:]))
            frame._section_summary.configure(wraplength=max(1, content_width - 26))
        if not label_widths:
            return
        for label in self.param_labels:
            label_width = label_widths.get(label.master)
            if label_width is not None and int(float(label.cget('wraplength'))) != label_width:
                label.configure(wraplength=label_width)

    def _register_param_extra(self, frame, widgets, keys=(), text='', predicate=None):
        self._param_extras.append((frame, widgets, tuple(keys), text, predicate))

    def _mos_current_plateau_active(self):
        return self._mos_resolved_mode() in ('curve','gfs')

    def _mark_mos_gate_stale(self):
        if hasattr(self, 'mos_gate_readout'):
            self.mos_gate_readout.set('当前 MOS 平台：待计算，旧工况值已清除。')

    def _update_mos_gate_readout(self, res):
        if res['op'].get('llc'):
            self._curve_gate_result = {}
            return
        gate = res['semi']['switch']['gate']
        self._curve_gate_result=gate
        self.mos_gate_readout.set(gate['label']+f"\nId,on={gate['I_on']:.4g} A → Vgp,on={gate['Vgp_on']:.4g} V\n"
                                 f"Id,off={gate['I_off']:.4g} A → Vgp,off={gate['Vgp_off']:.4g} V\n"
                                 f"Qgs,on/off={gate['Qgs_on']*1e9:.4g}/{gate['Qgs_off']*1e9:.4g} nC；Qgd={gate['Qgd_on']*1e9:.4g} nC\n"
                                 f"Qg(th)={gate['Qg_th']*1e9:.4g} nC；Qg,total={gate['Qg_on']*1e9:.4g} nC"+
                                 ('\n本工况含端点趋势外推，请结合规格书/实测校核。' if gate.get('extrapolations') or gate.get('charge_extrapolations') else ''))

    def _build_scheme_rows(self, frame, row, topology_labels, control_labels):
        self._control_labels = control_labels
        for name, var, values, attr in (
                ('拓扑', self.params['topology'], list(topology_labels.values()), 'topo_combo'),
                ('控制模式', self.params['control_mode'], list(control_labels.values()), 'ctrl_combo')):
            label = ttk.Label(frame, text=name, style='Param.TLabel')
            label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(3, 1))
            if attr == 'ctrl_combo':
                self._param_mode_display = tk.StringVar(value=var.get())
                var = self._param_mode_display
            combo = ttk.Combobox(frame, textvariable=var, values=values, state='readonly', width=18)
            if attr == 'ctrl_combo':
                combo.bind('<<ComboboxSelected>>', lambda _e: self.params['control_mode'].set(self._param_mode_display.get()))
            combo.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 5))
            setattr(self, attr, combo)
            self._register_param_extra(frame, [label, combo], text=name+' topology control_mode')
            row += 2
        bridge_label = ttk.Label(frame, text='LLC 原边桥式', style='Param.TLabel')
        bridge_label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(3, 1))
        if 'llc_bridge' not in self.params:
            self.params['llc_bridge'] = tk.StringVar(value='half')
        self._param_llc_bridge_display = tk.StringVar()
        self.llc_bridge_combo = ttk.Combobox(frame, textvariable=self._param_llc_bridge_display,
            values=tuple(LLC_BRIDGE_LABELS.values()), state='readonly')
        self.llc_bridge_combo.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 5))
        self.llc_bridge_combo.bind('<<ComboboxSelected>>', lambda _e: self.params['llc_bridge'].set(
            next(key for key, label in LLC_BRIDGE_LABELS.items()
                 if label == self._param_llc_bridge_display.get())))
        self.params['llc_bridge'].trace_add('write', lambda *_: self._parameter_context_changed())
        self._llc_bridge_widgets = (bridge_label, self.llc_bridge_combo)
        self._register_param_extra(frame, self._llc_bridge_widgets, text='LLC 半桥 全桥 llc_bridge',
                                   predicate=lambda:self._topo_key() == 'LLC')
        row += 2
        self.single_output_note = tk.StringVar()
        note = ttk.Label(frame, textvariable=self.single_output_note, style='Muted.TLabel', wraplength=350)
        note.grid(row=row, column=0, columnspan=4, sticky='ew')
        self._register_param_extra(frame, [note], text='输出配置 多绕组 outputs')
        row += 1
        label = ttk.Label(frame, text='显示工况（全部页面）', style='Param.TLabel')
        label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(6, 1))
        self._input_case_display = tk.StringVar(value='Vin min · 输入下限')
        self.input_case_combo = ttk.Combobox(frame, textvariable=self._input_case_display,
            values=('Vin min · 输入下限', 'Vin max · 输入上限'), state='readonly')
        self.input_case_combo.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 4))
        self.input_case_combo.bind('<<ComboboxSelected>>', lambda _e:
            self.params['input_voltage_case'].set('max' if self._input_case_display.get().startswith('Vin max') else 'min'))
        note = ttk.Label(frame, text='两端工况共用同一套器件。自动磁件设计以输入下限为参考，报告包含两端工况。',
            style='Muted.TLabel', wraplength=350, justify='left')
        note.grid(row=row+2, column=0, columnspan=4, sticky='ew', pady=(0, 4))
        self._register_param_extra(frame, [label, self.input_case_combo, note],
            ('V_in_min', 'V_in_max'), '输入电压 工况 Vin min max 波形')
        self.params['input_voltage_case'].trace_add('write', lambda *_: self._refresh_param_summaries())
        return row + 3

    def _build_clamp_parameter_rows(self, frame, row):
        flyback = lambda: self._topo_key() in ('FLYBACK', 'QR-FLYBACK')
        header = ttk.Label(frame, text='RCD 漏感钳位', style='TLabelframe.Label', padding=(2, 6, 2, 3))
        header.grid(row=row, column=0, columnspan=4, sticky='ew')
        self._register_param_extra(frame, [header], text='RCD 钳位 漏感 snubber', predicate=flyback)
        row += 1
        self._rcd_param_widgets = {}
        for key, label, symbol in (('rcd_K', '旧版漏感系数 K（非 kij）', 'K'),
                                   ('rcd_Kc', '钳位比 Vclamp/Vreflect', 'Kc'),
                                   ('rcd_dC', '钳位电压波动比例（0–1）', 'dC')):
            caption = ttk.Label(frame, text=label, style='Param.TLabel', wraplength=165)
            caption.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
            self.param_labels.append(caption)
            entry = ttk.Entry(frame, textvariable=self.params[key], width=8)
            limit_numeric_input(entry)
            entry.grid(row=row, column=1, columnspan=3, sticky='ew', padx=2, pady=3)
            self._rcd_param_widgets[key] = (caption, entry)
            active = (lambda: flyback() and not (hasattr(self, 'coupling_enabled') and
                      self.coupling_enabled.get() and self._topo_key() == 'FLYBACK' and
                      self._effective_feedback_mode() == 'SSR')) if key == 'rcd_K' else flyback
            self._register_param_extra(frame, [caption, entry], text=f'RCD 钳位 {label} {key} {symbol}', predicate=active)
            row += 1
        return row

    def _build_core_picker_rows(self, frame, row):
        from power_stage import DEFAULT_PARAMS
        self._init_custom_core_controls()
        toggle = ttk.Checkbutton(frame, text='启用电感磁芯与绕组设计（取消＝外购成品电感）',
                                 variable=self.params['inductor_design_enabled'])
        toggle.grid(row=row, column=0, columnspan=4, sticky='w', pady=5)
        self._register_param_extra(frame, [toggle], text='电感设计 一体成型 成品 外购',
                                   predicate=lambda:self._topo_key() in ('BUCK','BOOST','BUCK-BOOST'))
        row += 1
        bought_note = ttk.Label(frame, text='成品电感的感值在「② 功率级与钳位」填写。DCR 用于计算直流铜损，额定电流和附加损耗可选填，0 表示未提供。缺少磁件资料时，磁密和温升待评估。',
                                style='Muted.TLabel', wraplength=350, justify='left')
        bought_note.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
        self._register_param_extra(frame, [bought_note], text='成品电感 L DCR 损耗 电流', predicate=self._purchased_inductor)
        row += 1
        ttk_label = ttk.Label(frame, text='先选择材料与磁芯，再设置绕组。感值和匝比在「② 功率级与钳位」填写。', style='Muted.TLabel', wraplength=350)
        ttk_label.grid(row=row, column=0, columnspan=4, sticky='w', pady=3)
        self._register_param_extra(frame, [ttk_label], text='磁芯 材料 绕组', predicate=lambda:not self._purchased_inductor())
        row += 1
        self.params['core_shape'] = tk.StringVar(value='auto')
        self.params['core_choice_L'] = tk.StringVar(value='auto')
        self.params['core_material'] = tk.StringVar(value=DEFAULT_PARAMS['core_material'])
        def independent_core_visible():
            return self._topo_key()=='LLC' or (self._topo_key()=='ACF-FORWARD' and not self._multiple_active())
        for name, var, choices, attr, callback, predicate in (
                ('磁芯材料', self.params['core_material'], list(mag.STEINMETZ_MATERIALS), 'mat_combo', self.on_material_change, None),
                ('磁芯形状', self.params['core_shape'], ['auto']+mag.core_shape_list(), 'shape_combo', self.on_core_shape_change, None),
                ('磁芯型号', self.params['core_choice'], ['auto',CUSTOM_CORE]+list(mag.CORE_DB), 'core_combo', self.on_core_model_change, None),
                ('独立电感磁芯（正激输出／LLC Lr）', self.params['core_choice_L'],
                 ['auto',CUSTOM_CORE]+list(mag.CORE_DB), 'inductor_core_combo', None,independent_core_visible)):
            label = ttk.Label(frame, text=name, style='Param.TLabel', wraplength=150)
            label.grid(row=row, column=0, sticky='w', pady=3)
            combo = ttk.Combobox(frame, textvariable=var, values=choices, state='readonly', width=14)
            combo.grid(row=row, column=1, columnspan=3, sticky='ew', pady=3)
            setattr(self, attr, combo)
            if callback:
                combo.bind('<<ComboboxSelected>>', lambda _event, fn=callback: fn())
            logical_key = {'mat_combo': 'material', 'shape_combo': 'core_shape',
                           'core_combo': 'core_choice', 'inductor_core_combo': 'core_choice_L'}[attr]
            self._register_param_extra(frame, [label, combo], text=name+' '+logical_key,
                predicate=lambda original=predicate:not self._purchased_inductor() and (original is None or original()))
            row += 1
            if attr in ('core_combo','inductor_core_combo'):
                key='custom_core' if attr=='core_combo' else 'custom_core_L'
                editor=CoreGeometryEditor(frame,self._custom_core_vars[key],self._custom_core_edited,
                    '当前磁芯有效尺寸' if attr=='core_combo' else '独立电感磁芯有效尺寸')
                editor.frame.grid(row=row,column=0,columnspan=4,sticky='ew')
                self._custom_core_editors[key]=editor
                visible_core=(lambda:is_custom(self.params['core_choice'].get())) if key=='custom_core' else (
                    lambda:independent_core_visible() and is_custom(self.params['core_choice_L'].get()))
                self._register_param_extra(frame,[editor.frame],text=key+' 自定义 非标准 磁芯 Ae Ve Wa 尺寸 mm cm',
                    predicate=lambda original=visible_core:not self._purchased_inductor() and original())
                var.trace_add('write',self._custom_core_context_changed)
                row+=1
        return row

    def _build_feedback_rows(self, frame, row):
        cot_button=ttk.Button(frame,text='COT 控制、均流、保护与验收…',command=self._open_cot_settings)
        cot_button.grid(row=row,column=0,columnspan=4,sticky='ew',pady=5)
        self._register_param_extra(frame,[cot_button],text='COT 均流 限流 死区 动态 逐相 容差 验收',
                                   predicate=self._cot_active)
        row+=1
        label = ttk.Label(frame, text='补偿类型', style='Param.TLabel')
        label.grid(row=row, column=0, sticky='w', pady=3)
        self._param_controller_display = tk.StringVar(value=self.params['controller_type'].get())
        combo = ttk.Combobox(frame, textvariable=self._param_controller_display, values=('auto', 'type2', 'type3'), state='readonly', width=12)
        combo.bind('<<ComboboxSelected>>', lambda _e: self.params['controller_type'].set(self._param_controller_display.get()))
        self._param_controller_combo = combo
        combo.grid(row=row, column=1, columnspan=3, sticky='ew')
        self._register_param_extra(frame, [label, combo], text='补偿类型 controller_type 二型 三型',
                                  predicate=lambda: not self._cot_active() and self._topo_key() != 'LLC')
        row += 1
        row = self._add_param_link(frame, row, '在环路页可自动整定。SSR 保留五项零极点，MP6005 使用本组的 COMP 参数。',
                                   '查看环路 / 自动整定', 'tab_loop',
                                   ('BUCK', 'BOOST', 'BUCK-BOOST', *ISOLATED))
        row = self._add_param_link(frame, row, '在当前输入端点查看环路响应与负载阶跃。',
                                   '查看 LLC 环路与动态', 'tab_loop', ('LLC',))
        return row

    def _add_param_link(self, frame, row, text, caption, tab, topologies=()):
        label = ttk.Label(frame, text=text, style='Muted.TLabel', wraplength=350, justify='left')
        label.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(4, 2))
        button = ttk.Button(frame, text=caption, command=lambda: self._open_parameter_tab(tab))
        button.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 3))
        predicate = (lambda: self._topo_key() in topologies) if topologies else None
        if tab == 'tab_loop':
            predicate = lambda: not self._cot_active() and (not topologies or self._topo_key() in topologies)
        self._register_param_extra(frame, [label, button], text=text+' '+caption, predicate=predicate)
        return row + 2

    def _open_parameter_tab(self, tab):
        self._sync_topology_pages()
        target = getattr(self, tab)
        if str(self.nb.tab(target, 'state')) == 'hidden':
            self.status_var.set('当前拓扑或控制方式不适用此工具。')
            return
        self.nb.select(target)
        self._refresh_visible_tab()

    def _open_outputs_from_parameters(self):
        if self._topo_key() in ISOLATED:
            self.edit_outputs()

    def _parameter_context_changed(self):
        if not hasattr(self, '_param_display_vars'):
            return
        self._filter_params()
        if hasattr(self, 'nb') and hasattr(self, 'tab_comp'):
            self._sync_topology_pages()
        if not self._building and not self._inline_binding_busy:
            self.schedule_update()

    def _refresh_param_rows(self):
        for key in self._param_widgets:
            self._sync_param_field(key)
        topo, mode = self._presentation_context()
        cot = self._cot_active()
        llc = topo == 'LLC'
        phases = self._buck_phase_count() if topo == 'BUCK' else None
        label = ('每相功率电感 Lφ' if cot else '励磁电感 Lm' if topo in ('FLYBACK', 'QR-FLYBACK')
                 else '输出滤波电感 Lout' if topo == 'ACF-FORWARD' else '功率电感 L')
        if topo=='FLYBACK' and hasattr(self,'coupling_enabled') and self.coupling_enabled.get() and self._effective_feedback_mode()=='SSR':
            label = '原边自感 Lp（开路测量）'
        self._param_widgets['L'][0].configure(text=label+' *')
        self._param_widgets['f_sw'][0].configure(text=('每相目标频率 fsw *' if cot else
            '频率上限 fmax *' if topo == 'QR-FLYBACK' else
            '求解参考频率 fs,ref *' if llc else '开关频率 fsw *'))
        for _frame, header, keys in self._param_subgroups:
            if keys == ('Vf_diode', 'Rd_diode', 'Qrr'):
                header.configure(text='D1–D4 · 全桥整流二极管共用' if llc else
                    'D1 / D2 · 固定 Vf/Qrr 共用，曲线独立' if topo == 'ACF-FORWARD' else 'D1 · 输出整流器')
            elif keys[0] == 'Rds_on':
                header.configure(text='Q1–Q4 · 全桥主 MOS 共用' if llc and self.params['llc_bridge'].get() == 'full'
                    else 'Q1 / Q2 · 半桥主 MOS 共用' if llc else 'Q1 · 主开关 MOS')
            elif keys == ('Rds_aux', 'Qg_aux', 'Coss_aux'):
                header.configure(text='Q2 · 每相同步低侧 MOS' if cot else 'Q2 · 钳位 MOS')
        self._param_llc_bridge_display.set(LLC_BRIDGE_LABELS.get(self.params['llc_bridge'].get(), LLC_BRIDGE_LABELS['half']))
        if llc:
            for key, letter, unit in (('llc_kp', 'Kp', 'V/V' if mode == 'Hybrid Hysteretic' else 'Hz/V'),
                                      ('llc_ki', 'Ki', '1/s' if mode == 'Hybrid Hysteretic' else 'Hz/(V·s)')):
                self._param_widgets[key][0].configure(text=f'{META[key].label} {letter} · {unit}')
        self._param_widgets['A_sense'][1].configure(state='readonly' if self._psr_active() else 'normal')
        multiple = topo in ISOLATED and self.multi_enabled.get()
        for key in ('V_out', 'P_out'):
            self._param_widgets[key][1].configure(state='readonly' if multiple else 'normal')
        self._param_mode_display.set('Peak Current Mode (峰值电流模式)' if self._psr_active() else self.params['control_mode'].get())
        allowed = (('Voltage Mode', 'Hybrid Hysteretic') if llc else
                   ('Voltage Mode', 'Peak Current Mode', 'Constant On-Time') if topo == 'BUCK' else
                   ('Voltage Mode', 'Peak Current Mode'))
        modes = tuple(self._control_labels[key] for key in allowed if key in self._control_labels)
        self.ctrl_combo.configure(values=modes,
            state='disabled' if self._psr_active() or (phases is not None and phases > 1) else 'readonly')
        self._param_controller_display.set('type2 (MP6005)' if self._psr_active() else self.params['controller_type'].get())
        self._param_controller_combo.configure(state='disabled' if self._psr_active() else 'readonly')
        self.inductor_core_combo.configure(state='disabled' if multiple and topo == 'ACF-FORWARD' else 'readonly')
        self._sync_inline_output_context()
        self._sync_mos_curve_controls()
        self._sync_device_curve_controls()
        self._refresh_param_summaries()

    def _capacitor_bank_changed(self,side):
        self._cap_bank_active[side]=True
        if not self._building:
            self._cap_model_picker.refresh()
            self._refresh_param_summaries()
            self.schedule_update()

    def _capacitor_parameters(self):
        return {side+'_capacitors':editor.get() if self._cap_bank_active[side] else None
                for side,editor in self._cap_editors.items()}

    def _load_capacitor_parameters(self,cfg):
        from capacitor_banks import bank
        from config_io import decode_config
        from power_stage import DEFAULT_PARAMS
        p=dict(DEFAULT_PARAMS,**decode_config(cfg))
        for side,editor in self._cap_editors.items():
            editor.load(bank(p,side))
            self._cap_bank_active[side]=p.get(side+'_capacitors') is not None

    def _refresh_param_summaries(self):
        if not hasattr(self, '_param_summary_vars'):
            return
        def val(key, suffix=''):
            try:
                return display_number(self.get_param(key)) + suffix
            except (ValueError, KeyError, tk.TclError):
                return '待填写'
        topo, mode = self._presentation_context()
        cot = self._cot_active()
        llc = topo == 'LLC'
        case = 'max' if self.params['input_voltage_case'].get() == 'max' else 'min'
        if hasattr(self, '_input_case_display'):
            self._input_case_display.set('Vin max · 输入上限' if case == 'max' else 'Vin min · 输入下限')
        range_text = val('V_in_min')+'–'+val('V_in_max', ' V')
        state = '' if self._snapshot_valid else ' · 待计算'
        input_span = '' if val('V_in_min') == val('V_in_max') else f' · {range_text}'
        self.input_case_note.set(f"Vin {case} {val('V_in', ' V')}{input_span}{state}")
        multiple = topo in ISOLATED and self.multi_enabled.get()
        if multiple:
            demand = f'{range_text} · {len(self.output_config)} 路输出'
            self.single_output_note.set('已启用多路输出。各路参数在本侧栏对应分组中编辑。')
        else:
            demand = range_text+' → '+val('V_out', ' V')+' · '+val('P_out', ' W')
            self.single_output_note.set('各相并到同一输出。功率和电容组按整机填写，电感、频率和 MOS 参数按每相填写。' if cot else
                '隔离单路输出，副边采用四二极管全桥整流。' if llc else
                '单路输出。可启用最多 6 路绕组输出。' if topo in ISOLATED else '非隔离单路输出。')
        try:
            eta = display_number(self.get_param('eta_guess') * 100)+'%'
        except (ValueError, tk.TclError):
            eta = '待填写'
        summaries = {
            'spec': demand+' · 预设效率 '+eta+(' · MP6005 PWM 固定 250 kHz，轻载单独计算' if self._psr_active() else ''),
            'stage': val('buck_phases', ' 相')+' · 同步交错 / 每相电感' if cot else ('励磁' if topo in ('FLYBACK', 'QR-FLYBACK') else '输出电感')+' · '+('有源钳位' if topo == 'ACF-FORWARD' else 'RCD' if topo in ('FLYBACK', 'QR-FLYBACK') else '非隔离功率级'),
            'device': '预设 / 手工参数 · 栅极电荷法（*模型必需）',
            'capacitors': f"输入 {len(self._cap_editors['input'].values) if 'input' in self._cap_editors else 2} 颗 / "+('各路输出独立配置' if multiple else f"输出 {len(self._cap_editors['output'].values) if 'output' in self._cap_editors else 2} 颗电容")+' · 可增删',
            'drive': 'Vgs '+val('Vgs', ' V')+' · 分别设置开通和关断电阻',
            'sense': ('按每相采样电阻计算损耗' if cot else
                ('MP6005：PCM，采样增益固定11' if self._psr_active() else '电压模式' if mode == 'Voltage Mode' else '峰值电流模式')+' · 采样电阻仍计损耗'),
            'mag': '成品电感 · 按感值及厂家参数计算' if self._purchased_inductor() else '材料与磁芯 · 绕组与温升',
            'ctrl': 'COT 导通与交错时序' if cot else (('PSR-MP6005' if self._psr_active() else 'SSR')+f' · OUT{self.feedback_output.get() if multiple else 1}' if topo in ISOLATED else '非隔离反馈')+' · '+('type2（MP6005）' if self._psr_active() else self._controller_key()),
        }
        if llc:
            hhc = mode == 'Hybrid Hysteretic'
            summaries.update(
                spec=demand + ' · ' + LLC_BRIDGE_LABELS.get(self.params['llc_bridge'].get(), ''),
                stage='串联 Lr / Cr · 并联励磁 Lm · 副边全桥整流',
                device='原边桥臂共用 MOS 参数 · 副边共用整流参数',
                drive='共用 Vgs · 桥臂互补时序与换流死区',
                sense='Cr 电压检测 · 每半周期补偿斜坡' if hhc else '',
                ctrl='混合滞环 · 谐振电容电压与斜坡' if hhc else '电压模式 · 电压环与变频')
        for section, text in summaries.items():
            if section == 'ctrl' and 'fc_target' in self.params and not cot and not llc:
                text += ' · 整定 fc '+val('fc_target', ' Hz')+' · 整定 PM '+val('pm_target', '°')
            missing = [key for key in self._param_group_keys.get(section, []) if META[key].required and self._scalar_parameter_active(key)
                       and not (key == 'Vgp_off' and self._mos_current_plateau_active()) and not self._mos_charge_parameter_hidden(key)
                       and not self._output_owns_parameter(key)
                       and self._param_value_missing(key)]
            if missing:
                text = f'{len(missing)} 项必填数值待填写 · '+text
            self._param_summary_vars[section].set(text)
        for switch_key, var in self._param_status_vars.items():
            enabled = self.params[switch_key].get()
            var.set('已启用：参与当前模型' if enabled else '已停用：保留参数，不参与当前模型')

    def _param_value_missing(self, key):
        try:
            return not math.isfinite(self.get_param(key))
        except (ValueError, KeyError, tk.TclError):
            return True

    def _filter_parameter_panel(self, *, refresh_rows=True):
        if not hasattr(self, '_param_extras'):
            return
        Tooltip.hide_all(self.root)
        if refresh_rows:
            self._refresh_param_rows()
        search = self.param_search.get().strip().lower()
        topo, mode = self._presentation_context()
        flags = {key: self.params[key].get() for key in (*OPTION_NAMES, 'inductor_design_enabled')}
        psr_active = self._psr_active()
        mos_mode = self._mos_resolved_mode()
        layout = {frame: {} for frame in self._param_sections.values()}
        visible_keys = set()
        for key, widgets in self._param_widgets.items():
            section = widgets[0].master
            # V_in is a compatibility variable. The input range supplies its editor.
            allowed = (key != 'V_in' and key not in DEPRECATED_RD and key not in CAPACITOR_FIELDS
                       and visible(key, topo, mode, True, flags))
            if allowed:
                allowed = not (self._mos_charge_parameter_hidden(key) or self._output_owns_parameter(key)
                               or (psr_active and key in PSR_COMPATIBILITY)
                               or (key == 'Vgp_off' and mos_mode in ('curve', 'gfs'))
                               or (key == 'gfs' and mos_mode != 'gfs')
                               or (key == 'mos_curve_vds' and (mos_mode != 'curve'
                                   or self._mos_miller_curve.get('kind') != 'output_family')))
            if search and allowed:
                spec = META[key]
                terms = ' '.join((key, spec.label, spec.symbol, widgets[0].cget('text'), section._section_title,
                                  self._param_search_terms[key], self._param_unit_vars[key].get()))
                allowed = search_matches(search, terms)
            layout[section].update((widget, allowed) for widget in widgets)
            if allowed:
                visible_keys.add(key)
        for frame, widgets, keys, text, predicate in self._param_extras:
            allowed = predicate is None or predicate()
            if allowed and keys:
                allowed = not (set(keys).issubset(CAPACITOR_FIELDS) or all(self._output_owns_parameter(key) for key in keys))
            # Optional switches stay visible even when their child fields are
            # disabled. Searching never exposes disabled, unused values.
            if allowed and search:
                allowed = (search_matches(search, text+' '+frame._section_title)
                           or any(key in visible_keys or search_matches(search, key) for key in keys))
            layout[frame].update((widget, allowed) for widget in widgets)
        for frame, header, keys in self._param_subgroups:
            allowed = any(key in visible_keys for key in keys)
            # A disabled optional subgroup still contains its enable switch.
            layout[frame][header] = allowed or any(
                layout[frame].get(self._param_switches.get(OPTIONAL.get(key)), False) for key in keys)
        self._param_row_layout = layout
        next_container = None
        # Reinsert hidden sections in order without disturbing mapped siblings.
        for section in reversed(SECTION_ORDER):
            next_container = self._apply_parameter_section(self._param_sections[section], bool(search), next_container)
        self._schedule_parameter_scrollregion()

    def _apply_parameter_section(self, frame, searching=False, before=None):
        rows = self._param_row_layout[frame]
        expanded = searching or frame not in self._folded_sections
        current_rows = set(frame.grid_slaves())
        has_content = expanded and (any(rows.values()) or bool(current_rows.difference(rows)))
        layout_changed = False
        for widget, visible_row in rows.items():
            if (expanded and visible_row) != (widget in current_rows):
                widget.grid() if expanded and visible_row else widget.grid_remove()
                layout_changed = True
        if layout_changed:
            frame._parameter_wrap_signature = None

        container = frame._section_container
        container_mapped = bool(container.winfo_manager())
        padding = (0, 9 if has_content else 4)
        if has_content != bool(frame.winfo_manager()):
            if has_content:
                frame.pack(fill='x')
                frame._section_summary.pack(fill='x', before=frame)
            else:
                frame.pack_forget()
                frame._section_summary.pack_forget()
            frame._section_header.configure(text=('▼ ' if has_content else '▶ ') + frame._section_title,
                                            padding=(9, 6 if has_content else 4))
            if container_mapped:
                container.pack_configure(pady=padding)
        if searching and not has_content:
            if container_mapped:
                container.pack_forget()
            return before
        if not container_mapped:
            placement = {'before': before} if before is not None else {}
            container.pack(fill='x', pady=padding, **placement)
        return container
