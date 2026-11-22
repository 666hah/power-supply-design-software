"""Draw the controller's signal schematic on a resizable Tk canvas."""
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from controller_logic import display_value, state_note
from spice_export import SETTINGS


INK = '#263747'
MUTED = '#53677b'
ACTIVE = '#1a60aa'
ACTIVE_FILL = '#e8f2ff'
BORDER = '#b5c5d3'
SIGNAL_TONES = {'protection': '#963e36', 'protect': '#963e36', 'power': '#546a7c',
                'external': '#546a7c', 'muted': '#65788b'}


class ControllerLogicPanel(ttk.Frame):
    def __init__(self, parent, *, values, design, available_keys=None):
        super().__init__(parent, padding=(10, 0, 0, 0), width=640)
        from controller_logic import acf_definition, cot_definition, definition, nonisolated_definition, qr_definition
        from cot_settings import active as cot_active

        self.values = values
        self.design = design
        topology = design.get('topology')
        if cot_active(design):
            self.definition = cot_definition()
        else:
            self.definition = {
                'QR-FLYBACK': qr_definition, 'ACF-FORWARD': acf_definition,
                'BUCK': nonisolated_definition, 'BOOST': nonisolated_definition,
            }.get(topology, definition)()
        self.nodes = self.definition['nodes']
        self.help = {key: (field['node'], field['purpose'], field['meaning'])
                     for key, field in self.definition['parameters'].items()}
        available = self.help if available_keys is None else available_keys
        self.available_keys = tuple(key for key in available if key in self.help)
        self.active_key = next(iter(self.available_keys), next(iter(self.help)))
        self.active_node = self.help[self.active_key][0]
        self._job = None
        self._layout_key = None
        self._fit_scale = .7
        self._zoom = None
        self._timer_root = self._root()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        ui_font = tkfont.nametofont('TkDefaultFont', root=self)
        family = ui_font.cget('family')
        font_size = max(12, min(16, abs(int(ui_font.cget('size')))))
        caption = (family, -font_size)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        ttk.Label(toolbar, text='控制器功能框图', font=(family, -max(14, font_size), 'bold')).pack(side='left')
        ttk.Button(toolbar, text='适合窗口', command=self._fit, style='Controller.TButton').pack(side='right', padx=(4, 0))
        ttk.Button(toolbar, text='+', width=3, command=lambda: self._change_zoom(1.2),
                   style='Controller.TButton').pack(side='right')
        ttk.Button(toolbar, text='−', width=3, command=lambda: self._change_zoom(1 / 1.2),
                   style='Controller.TButton').pack(side='right')
        self.zoom_label = ttk.Label(toolbar, width=6, anchor='e', foreground=MUTED, font=caption)
        self.zoom_label.pack(side='right', padx=(0, 5))

        view = ttk.Frame(self)
        view.grid(row=4, column=0, sticky='nsew', pady=(7, 0))
        view.columnconfigure(0, weight=1)
        view.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(view, background='white', width=430, height=210,
                                highlightthickness=1, highlightbackground=BORDER)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.xscroll = ttk.Scrollbar(view, orient='horizontal', command=self.canvas.xview)
        self.yscroll = ttk.Scrollbar(view, orient='vertical', command=self.canvas.yview)
        self.xscroll.grid(row=1, column=0, sticky='ew')
        self.yscroll.grid(row=0, column=1, sticky='ns')
        self.xscroll.grid_remove()
        self.yscroll.grid_remove()
        self.canvas.configure(xscrollcommand=self.xscroll.set, yscrollcommand=self.yscroll.set)
        self.canvas.bind('<Configure>', self._schedule)
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Shift-MouseWheel>', self._wheel)
        self.canvas.bind('<Button-4>', self._wheel)
        self.canvas.bind('<Button-5>', self._wheel)
        self.canvas.bind('<Button-1>', self._click)
        self.canvas.bind('<Motion>', self._set_cursor)

        self.heading = ttk.Label(self, style='ResultConclusion.TLabel', foreground=ACTIVE,
                                 font=(family, -max(13, font_size), 'bold'))
        self.heading.grid(row=1, column=0, sticky='ew', pady=(2, 3))
        self.description = ttk.Label(self, justify='left', wraplength=500, font=caption)
        self.description.grid(row=2, column=0, sticky='ew')
        self.condition = ttk.Label(self, foreground='#8d530a', justify='left', wraplength=500, font=caption)
        self.condition.grid(row=3, column=0, sticky='ew', pady=(3, 0))
        self.bind('<Configure>', self._wrap)
        self.bind('<Destroy>', self._destroy, add='+')
        self._schedule()

    def _wrap(self, event):
        if event.widget is self:
            for label in (self.heading, self.description, self.condition):
                label.configure(wraplength=max(180, event.width - 22))

    def select(self, key):
        if key in self.help:
            self.active_key = key
            self.active_node = self.help[key][0]
            self._schedule()

    def _select_block(self, node):
        if node != self.active_node:
            self.active_node = node
            self.active_key = next((key for key in self.available_keys if self.help[key][0] == node), None)
            self._schedule()

    def _click(self, _event):
        tags = self.canvas.gettags('current')
        key = next((tag[4:] for tag in tags if tag.startswith('key:')), None)
        if key in self.help:
            self.select(key)
            return
        node = next((tag[5:] for tag in tags if tag.startswith('node:')), None)
        if node:
            self._select_block(node)

    def _set_cursor(self, _event):
        clickable = any(tag.startswith('node:') for tag in self.canvas.gettags('current'))
        cursor = 'hand2' if clickable else ''
        if self.canvas.cget('cursor') != cursor:
            self.canvas.configure(cursor=cursor)

    def refresh(self):
        self._schedule()

    def _schedule(self, _event=None):
        if self._job is None:
            self._job = self._timer_root.after(35, self._draw)

    def _destroy(self, event):
        if event.widget is self and self._job is not None:
            self._timer_root.after_cancel(self._job)
            self._job = None

    def _fit(self):
        self._zoom = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._schedule()

    def _change_zoom(self, factor):
        base = self._zoom if self._zoom is not None else self._fit_scale
        self._zoom = min(2.25, max(.58, base * factor))
        self._schedule()

    def _wheel(self, event):
        horizontal = bool(event.state & 1)
        view = self.canvas.xview if horizontal else self.canvas.yview
        scroll = self.canvas.xview_scroll if horizontal else self.canvas.yview_scroll
        lo, hi = view()
        if hi - lo < .999:
            up = event.num == 4 or (event.num != 5 and getattr(event, 'delta', 0) > 0)
            scroll(-1 if up else 1, 'units')
            return 'break'
        return None

    def _schematic(self, values):
        definition = self.definition
        variants = definition.get('schematic_variants', {})
        if variants:
            default = 3 if self.design.get('topology') == 'BOOST' else (
                1 if self.design.get('control_mode') == 'Voltage Mode' else 2)
            try:
                profile = int(float(str(values.get('niso_profile', 0)).split(' ·')[0])) or default
            except (TypeError, ValueError, OverflowError):
                profile = default
            if str(profile) in variants:
                return variants[str(profile)]
        if self.design.get('control_mode') == 'Voltage Mode' and 'schematic_voltage' in definition:
            return definition['schematic_voltage']
        return definition['schematic']

    def _update_help(self, values):
        if self.active_key:
            key = self.active_key
            _, purpose, meaning = self.help[key]
            parameter = self.definition['parameters'][key]
            title = parameter.get('label', key)
            number = display_value(key, values, self.design) if key in SETTINGS else ''
            summary = f'{title}  ·  {number}' if number else title
            description = '\n'.join(dict.fromkeys(text for text in (purpose, meaning) if text))
            note = state_note(key, values)
        else:
            node = next((row for row in self.nodes if row['id'] == self.active_node), None)
            summary = node['title'] if node else ''
            description = '\n'.join(node['body']) if node else ''
            note = ''
        self.heading.configure(text=summary)
        self.description.configure(text=description)
        self.condition.configure(text=note)
        if note:
            self.condition.grid()
        else:
            self.condition.grid_remove()

    def _draw(self):
        self._job = None
        values = self.values()
        self._update_help(values)
        schematic = self._schematic(values)
        canvas = self.canvas
        viewport_w = canvas.winfo_width() - 2
        viewport_h = canvas.winfo_height() - 2
        if viewport_w <= 1 or viewport_h <= 1:
            return
        logical_w, logical_h = schematic['width'], schematic['height']
        self._fit_scale = min(viewport_w / logical_w, viewport_h / logical_h)
        scale = self._fit_scale if self._zoom is None else self._zoom
        rendered_w, rendered_h = round(logical_w * scale), round(logical_h * scale)
        for scrollbar, content, viewport in (
            (self.xscroll, rendered_w, viewport_w), (self.yscroll, rendered_h, viewport_h),
        ):
            if content > viewport + 2:
                scrollbar.grid()
            else:
                scrollbar.grid_remove()
        self.zoom_label.configure(text=f'{scale:.0%}')
        layout_key = (id(schematic), self.active_node, self.active_key, viewport_w, viewport_h, scale)
        if layout_key == self._layout_key:
            return
        self._layout_key = layout_key
        canvas.delete('all')
        canvas.configure(scrollregion=(0, 0, max(rendered_w, viewport_w), max(rendered_h, viewport_h)))
        painter = _SchematicPainter(canvas, scale, max(0, (viewport_w - rendered_w) / 2),
                                    max(0, (viewport_h - rendered_h) / 2))
        painter.draw(schematic, self.active_node, self.active_key)


class _SchematicPainter:
    def __init__(self, canvas, scale, offset_x, offset_y):
        self.canvas = canvas
        self.scale = scale
        self.offset_x = offset_x
        self.offset_y = offset_y

    def xy(self, *points):
        return tuple(value for x, y in points
                     for value in (self.offset_x + x * self.scale, self.offset_y + y * self.scale))

    def text(self, x, y, label, *, size=16, color=INK, weight='normal', anchor='center', tags=()):
        return self.canvas.create_text(*self.xy((x, y)), text=label, anchor=anchor, justify='center',
            fill=color, font=('Microsoft YaHei UI', -max(8, round(size * self.scale)), weight), tags=tags)

    def draw(self, schematic, active, parameter):
        c = self.canvas
        scale = self.scale
        x, y, w, h = schematic['boundary']
        c.create_rectangle(*self.xy((x, y), (x + w, y + h)), fill='#fbfdff',
                           outline=BORDER, dash=(5, 3))
        if schematic.get('title'):
            self.text(x + 10, y + 8, schematic['title'], anchor='nw', color=MUTED, weight='bold')

        for route in schematic['routes']:
            tone = SIGNAL_TONES.get(route.get('tone'), MUTED)
            arrow = 'last' if route.get('arrow', True) else 'none'
            c.create_line(*self.xy(*route['points']), fill=tone, width=max(1, 1.55 * scale),
                          arrow=arrow, arrowshape=tuple(max(2, round(v * scale)) for v in (6, 8, 3)))
        for x, y in schematic.get('junctions', ()):
            c.create_oval(*self.xy((x - 2.6, y - 2.6), (x + 2.6, y + 2.6)), outline='', fill=INK)
        for item in schematic['items']:
            scoped = item.get('focus_fields')
            selected = parameter in scoped if scoped is not None and parameter else item.get('key') == active
            self.item(item, active is not None and selected)
        for route in schematic['routes']:
            if route.get('label') and route.get('label_at'):
                self.text(*route['label_at'], route['label'], size=12,
                          color=SIGNAL_TONES.get(route.get('tone'), MUTED))

    def item(self, item, selected):
        c = self.canvas
        x, y, w, h = (item[key] for key in ('x', 'y', 'w', 'h'))
        cx, cy = x + w / 2, y + h / 2
        tags = (f"node:{item['key']}",) if item.get('key') else ()
        if item.get('parameter'):
            tags += (f"key:{item['parameter']}",)
        kind = item['kind']
        color = ACTIVE if selected else INK
        style = dict(outline=color, fill=ACTIVE_FILL if selected else 'white',
                     width=max(1, (2 if selected else 1.3) * self.scale), tags=tags)
        label_x = cx
        if kind == 'pin':
            c.create_oval(*self.xy((cx - 4.2, cy - 4.2), (cx + 4.2, cy + 4.2)), **style)
            left = item.get('side', 'left') == 'left'
            self.text(cx + (-9 if left else 9), cy, item['label'], size=15, color=color,
                      anchor='e' if left else 'w', weight='bold', tags=tags)
            return
        if kind in ('comparator', 'driver'):
            c.create_polygon(*self.xy((x, y), (x, y + h), (x + w, cy)), **style)
            label_x = x + (.29 if kind == 'driver' else .36) * w
        elif kind == 'sum':
            c.create_oval(*self.xy((x, y), (x + w, y + h)), **style)
        elif kind != 'note':
            c.create_rectangle(*self.xy((x, y), (x + w, y + h)), **style)
        detail = item.get('detail')
        label = item['label']
        size = 11 if kind == 'driver' else 14 if kind == 'note' else 16
        self.text(label_x, cy - (9 if detail else 0), label, size=size,
                  color=color, weight='bold' if kind != 'note' or selected else 'normal', tags=tags)
        if detail:
            self.text(label_x, cy + 11, detail, size=12, color=color if selected else MUTED, tags=tags)
        for pin in item.get('pins', ()):
            self.text(pin['x'], pin['y'], pin['name'], size=13, color=color, weight='bold', tags=tags)
