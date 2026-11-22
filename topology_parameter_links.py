"""Resolve desktop schematic and BOM designators to existing input widgets."""
from collections import defaultdict
from dataclasses import dataclass
import re
from tkinter import ttk

from capacitor_banks import output_ref


_FIELDS = {
    'J1': ('V_in_min', 'V_in_max'),
    'J2': ('V_out', 'P_out', 'ripple_target'),
    'R_LOAD': ('P_out',),
    'Q1': ('Rds_on', 'Coss', 'Qg', 'Vth', 'gfs', 'mos_curve_vds', 'Vgp_on', 'Vgp_off',
           'Qg_th', 'Qgs', 'Qgd', 'Rg', 'k_sw'),
    'Q2': ('Rds_aux', 'Qg_aux', 'Coss_aux'),
    'R_S1': ('Rs',),
    'D1': ('Vf_diode', 'Qrr'),
    'D2': ('Vf_diode', 'Qrr'),
    'D_IN': ('Vf_din',),
    'D_OUT': ('Vf_dout',),
    'L1': ('L', 'inductor_dcr', 'inductor_rated_current', 'inductor_saturation_current',
           'inductor_extra_loss'),
    'C_CL1': ('C_clamp', 'ESR_clamp'),
}
_RAIL_FIELDS = {
    'J_O': _FIELDS['J2'], 'R_LOAD': _FIELDS['R_LOAD'],
    'D_O': _FIELDS['D1'], 'D_F': _FIELDS['D2'], 'D_B': _FIELDS['D_OUT'],
    'L_O': ('L', 'core_choice_L'),
}
_RAIL_REF = re.compile(r'(J_O|R_LOAD|D_O|D_F|D_B|L_O)([1-6])')
_PSR_FIELDS = {
    'N_A': ('psr_Na', 'psr_aux_target'), 'R_FBH': ('psr_RfbH',),
    'R_FBL': ('psr_RfbL',), 'R_REG': ('psr_Rreg',), 'R_COMP': ('psr_Rcomp',),
    'C_COMP': ('psr_Ccomp',), 'C_POLE': ('psr_Cpole',), 'U_PSR': ('psr_Vcc',),
}
_RCD_FIELDS = {'R_SN1': ('rcd_Kc', 'rcd_K'), 'C_SN1': ('rcd_dC', 'rcd_Kc'),
               'D_SN1': ('rcd_Kc',)}
_TRANSFORMER_FIELDS = ('Np', 'd_wire_p', 'n_strand_p', 'parallel_wires_p', 'Ns',
                       'd_wire_s', 'n_strand_s', 'parallel_wires_s', 'mu_r', 'N')
_LLC_FIELDS = {
    **{f'Q{i}': ('Rds_on', 'Coss', 'Qg', 'llc_qoss') for i in range(1, 5)},
    **{f'D{i}': ('Vf_diode', 'llc_rect_r', 'llc_diode_cj') for i in range(1, 5)},
    'L_R': ('llc_lr','llc_tank_r','llc_lr_leakage_H','llc_lr_turns','llc_lr_strands','llc_lr_wire_diameter',
            'llc_lr_design_peak','llc_lr_min_ae','llc_lr_bobbin_radius','llc_lr_window_width','llc_lr_window_height'),
    'C_R': ('llc_cr',),
    'T1': ('llc_lm', 'N', *_TRANSFORMER_FIELDS[:-1]),
}


@dataclass(frozen=True)
class _Target:
    fields: tuple
    editor: object = None
    index: int = 0


class TopologyParameterLinks:
    def __init__(self, app, on_select):
        self.app = app
        self.on_select = on_select
        self.selected = None
        self._located_ref = None
        self._targets = {}
        self._widget_refs = {}
        self._bank_refs = {}
        self._bound_widgets = set()
        self._bound_banks = set()
        self._highlighted = {}
        self._style = ttk.Style(app.root)
        self._sections = {frame: key for key, frame in app._param_sections.items()}

    def _groups(self, widgets, keys):
        return tuple(tuple(widgets[key]) for key in keys if key in widgets)

    def _resolve(self, ref):
        app = self.app
        if app._topo_key() == 'LLC':
            if ref == 'U_CTRL':
                return self._groups(app._param_widgets,
                    ('llc_fmin', 'llc_fmax', 'llc_kp', 'llc_ki', 'llc_hhc_sense', 'llc_hhc_ramp'))
            if ref in _LLC_FIELDS:
                return self._groups(app._param_widgets, _LLC_FIELDS[ref])
        if ref in _PSR_FIELDS:
            return self._groups(app._inline_psr_widgets, _PSR_FIELDS[ref])
        if ref in _RCD_FIELDS:
            return self._groups(app._rcd_param_widgets, _RCD_FIELDS[ref])
        match = _RAIL_REF.fullmatch(ref)
        if match:
            kind, number = match.groups()
            keys = _RAIL_FIELDS[kind]
            if app._inline_multiple_active():
                return self._groups(app._inline_output_widgets, ((int(number)-1, key) for key in keys))
            # With single-output PSR the schematic uses OUT1 designators.
            return self._groups(app._param_widgets, keys) if number == '1' else ()
        if ref == 'T1':
            inductance = 'Lm_forward' if app._topo_key() == 'ACF-FORWARD' else 'L'
            return self._groups(app._param_widgets, (*_TRANSFORMER_FIELDS, inductance))
        if ref == 'U_FB':
            return ((app.feedback_pick,),)
        if ref == 'U_CTRL':
            keys = ('cot_ton_s', 'cot_min_off_s', 'buck_phases') if app._cot_active() else ('f_sw', 'A_sense', 'Vm')
            return self._groups(app._param_widgets, keys)
        return self._groups(app._param_widgets, _FIELDS.get(ref, ()))

    def set_rows(self, rows):
        """Refresh the active designators without rebuilding or touching inputs."""
        refs = {row['ref'] for row in rows}
        app = self.app
        input_bank = app._cap_editors['input']
        output_bank = app._cap_editors['output']
        banks = (input_bank, *app._inline_cap_editors.values()) if app._inline_multiple_active() else (input_bank, output_bank)
        self._bank_refs = {}
        targets = {}
        for editor in banks:
            positions = {}
            for index in range(len(editor.values)):
                ref = editor.reference(index)
                if editor is output_bank and ref not in refs:
                    ref = output_ref(1, index + 1, True)
                if ref in refs:
                    positions[index] = ref
                    targets[ref] = _Target(tuple(editor.fields.values()), editor, index)
            if positions:
                self._bank_refs[editor] = positions
                self._bind_bank(editor)

        self._widget_refs = defaultdict(list)
        for row in rows:
            ref = row['ref']
            if ref in targets:
                continue
            fields = self._resolve(ref)
            if fields:
                targets[ref] = _Target(fields)
                for group in fields:
                    for widget in group:
                        self._widget_refs[widget].append(ref)
                        self._bind_widget(widget)
        self._targets = targets
        self.select(self.selected if self.selected in refs else None)

    def _bind_widget(self, widget):
        if widget in self._bound_widgets:
            return
        sequence = '<ButtonRelease-1>' if isinstance(widget, ttk.Label) else '<FocusIn>'
        widget.bind(sequence, self._on_field_select, add='+')
        self._bound_widgets.add(widget)

    def _bind_bank(self, editor):
        if editor in self._bound_banks:
            return
        editor.on_selection = lambda index: self._on_bank_select(editor, index)
        for label, entry in editor.fields.values():
            label.bind('<ButtonRelease-1>', lambda _event: self._on_bank_select(editor, editor.index), add='+')
            entry.bind('<FocusIn>', lambda _event: self._on_bank_select(editor, editor.index), add='+')
        self._bound_banks.add(editor)

    def _on_field_select(self, event):
        refs = self._widget_refs.get(event.widget)
        if refs:
            # Preserve current part when one value is shared (e.g. rectifier
            # and freewheel diode, or an output port and its modelled load).
            ref = self.selected if self.selected in refs else refs[0]
            self.on_select(ref)

    def _on_bank_select(self, editor, index):
        ref = self._bank_refs.get(editor, {}).get(index)
        if ref is not None:
            return self.on_select(ref)

    def _anchor(self, widget):
        """Return the section and actual scroll anchor of an applicable input."""
        owner = widget
        while owner.master is not None:
            section_frame = owner.master
            if section_frame in self._sections:
                options = self.app._param_row_layout.get(section_frame, {})
                if options.get(owner, False):
                    return self._sections[section_frame], widget
                return None
            owner = section_frame
        return None

    def locate(self, ref):
        """Return True for a located input, None for a reference, False for invalid draft."""
        target = self._targets.get(ref)
        if target is None:
            return None
        if target.editor is not None and not target.editor.select_index(target.index):
            return False
        app = self.app
        if app.param_search.get():
            app.param_search.set('')
        rows = [(anchor, field) for field in target.fields
                if (anchor := self._anchor(field[0])) is not None]
        if not rows:
            return None
        (section, widget), _ = rows[0]
        context = tuple(control for (owner, _), field in rows if owner == section for control in field)
        app._set_parameter_pane_visible(True)
        app._focus_inline_section(section, widget=widget, context=context)
        self._located_ref = ref
        return True

    def select(self, ref):
        """Change the input highlight without moving focus or triggering a solve."""
        if self._located_ref != ref and self._located_ref is not None:
            self.app._cancel_parameter_scroll()
            self._located_ref = None
        self.selected = ref
        target = self._targets.get(ref)
        captions = {row[0] for row in target.fields if isinstance(row[0], ttk.Label)} if target else set()
        for widget in self._highlighted.keys() - captions:
            widget.configure(style=self._highlighted.pop(widget))
        for widget in captions - self._highlighted.keys():
            base = widget.cget('style')
            style = 'TopologyLinked.' + (base or 'TLabel')
            self._style.configure(style, foreground='#ffffff', background='#224b89')
            self._highlighted[widget] = base
            widget.configure(style=style)
