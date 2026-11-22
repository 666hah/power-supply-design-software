"""Native, pannable view of the desktop schematic's vector artists."""
from tkinter import Canvas, Menu, StringVar, TclError, Toplevel, font, ttk

from matplotlib.colors import to_hex
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Polygon
from matplotlib.text import Text


_SELECTED_INK = '#0b3d86'


def _color(color):
    if color is None or isinstance(color, str) and color.lower() == 'none':
        return ''
    rgba = to_hex(color, keep_alpha=True)
    return rgba[:7] if rgba[-2:] != '00' else ''


class TopologyCanvas(ttk.Frame):
    """Pan and zoom native items. Electrical edits alone replace the scene."""

    def __init__(self, parent, selected=None, *, fit_label='完整回路', preferred_height=360,
                 expand_label=None, expand_region=None):
        super().__init__(parent)
        self._select_callback = selected
        self._fit_label = fit_label
        self._expand_region = expand_region
        self._can_expand = expand_label is not None
        self._scene_source = None
        self._large_view = None
        self._extent = None
        self._regions = {}
        self._focus_region = None
        self._fonts = {}
        self._items = {}
        self._refs = {}
        self.selection = None
        self._drag_start = None
        self._dragged = False
        self.scale = 1.
        self._fit = True
        self._layout_job = None
        self._grid_job = None
        self._timer_owner = self.winfo_toplevel()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        tools = ttk.Frame(self, padding=(5, 2))
        tools.grid(row=0, column=0, columnspan=2, sticky='ew')
        self._zoom_tools = zoom_tools = ttk.Frame(tools)
        zoom_tools.grid(row=0, column=0, sticky='w')
        self._region_tools = ttk.Frame(tools)
        self._region_picker = ttk.Menubutton(tools, text='定位图块')
        self._region_menu = Menu(self._region_picker, tearoff=False)
        self._region_picker.configure(menu=self._region_menu)
        self._region_layout = None
        tools.bind('<Configure>', lambda event: self._layout_region_tools(event.width), add='+')
        button_style = 'TopologyTool.TButton'
        ttk.Button(zoom_tools, text='−', width=3, command=lambda: self.zoom(1/1.25), style=button_style).pack(side='left')
        self.zoom_text = StringVar(self, '100%')
        ttk.Label(zoom_tools, textvariable=self.zoom_text, width=7, anchor='center', style='TopologyMeta.TLabel').pack(side='left')
        ttk.Button(zoom_tools, text='+', width=3, command=lambda: self.zoom(1.25), style=button_style).pack(side='left')
        ttk.Button(zoom_tools, text=fit_label, width=-1, command=self.fit, style=button_style).pack(side='left', padx=5)
        if expand_label:
            ttk.Button(zoom_tools, text=expand_label, width=-1, command=self.show_large,
                       style=button_style).pack(side='left', padx=(0, 4))
        self._region_buttons = {}
        for key, label in (('power', '功率级'), ('feedback_loop', '反馈与芯片'),
                           ('compensation', '反馈补偿'), ('controller', '控制逻辑')):
            self._region_buttons[key] = ttk.Button(
                self._region_tools, text=label, width=-1,
                command=lambda region=key: self.fit(region), style=button_style)

        self.canvas = c = Canvas(self, background='#fbfdff', highlightthickness=0, takefocus=True,
                                 height=preferred_height, width=420)
        c.grid(row=1, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(self, command=lambda *args: self._scroll(c.yview, *args))
        vertical.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=lambda *args: self._scroll(c.xview, *args))
        horizontal.grid(row=2, column=0, sticky='ew')
        def publish_scroll(bar, start, end):
            bar.set(start, end)
            if self._grid_job is None:
                self._grid_job = self._timer_owner.after_idle(self._draw_grid)
        c.configure(xscrollcommand=lambda a,b:publish_scroll(horizontal,a,b),
                    yscrollcommand=lambda a,b:publish_scroll(vertical,a,b))
        c.bind('<Configure>', self._queue_layout)
        c.bind('<ButtonPress-1>', self._press)
        c.bind('<B1-Motion>', self._drag)
        c.bind('<ButtonRelease-1>', self._release)
        c.bind('<ButtonPress-2>', self._press)
        c.bind('<B2-Motion>', self._drag)
        c.bind('<ButtonRelease-2>', self._release)
        c.bind('<MouseWheel>', self._wheel)
        c.bind('<Button-4>', lambda event: self.zoom(1.18, event.x, event.y))
        c.bind('<Button-5>', lambda event: self.zoom(1/1.18, event.x, event.y))
        for key, factor in (('plus', 1.25), ('equal', 1.25), ('minus', .8)):
            c.bind(f'<Key-{key}>', lambda _event, f=factor: self.zoom(f))
        c.bind('<Key-0>', lambda _event: self.fit())
        c.bind('<Destroy>', self._cancel_layout)

    def clear(self):
        self.canvas.delete('scene')
        self._scene_source = None
        if self._large_view is not None:
            self._large_view.clear()
        self._extent = None
        self._focus_region = None
        self._set_regions({})
        self._fit = True
        self._refs.clear()
        self._items.clear()
        self.selection = None
        self.zoom_text.set('100%')

    def _set_regions(self, regions):
        previous = self._regions
        self._regions = regions
        if regions.keys() != previous.keys():
            self._region_menu.delete(0, 'end')
            for button in self._region_buttons.values():
                button.pack_forget()
            for key, button in self._region_buttons.items():
                if key in regions:
                    button.pack(side='left', padx=(0, 3))
                    self._region_menu.add_command(label=button.cget('text'), command=button.invoke)
            self._layout_region_tools(self._region_tools.master.winfo_width())

    def _layout_region_tools(self, width):
        base_width = self._zoom_tools.winfo_reqwidth() + 10
        region_width = sum(button.winfo_reqwidth() + 3 for key, button in self._region_buttons.items()
                           if key in self._regions)
        if not self._regions:
            layout = None
        elif width >= base_width + region_width:
            layout = 'buttons'
        else:
            layout = 'second_row' if width < base_width + self._region_picker.winfo_reqwidth() else 'picker'
        if layout == self._region_layout:
            return
        self._region_layout = layout
        self._region_tools.grid_remove()
        self._region_picker.grid_remove()
        if layout == 'buttons':
            self._region_tools.grid(row=0, column=1, sticky='w')
        elif layout:
            row = int(layout == 'second_row')
            self._region_picker.grid(row=row, column=1-row, sticky='w')

    def set_scene(self, axis, hits, *, regions=None):
        """Copy geometry once; future navigation only moves native items."""
        old_extent = self._extent
        extent = self._extent = (*axis.get_xlim(), *axis.get_ylim())
        regions = regions or {}
        if self._can_expand:
            self._scene_source = (axis, hits, regions)
        if old_extent is None or self._focus_region not in regions:
            self._focus_region = None
        self._set_regions(regions)
        c = self.canvas
        center = (c.canvasx(c.winfo_width()/2), c.canvasy(c.winfo_height()/2))
        c.delete('scene')
        self._refs.clear()
        self._items.clear()
        self.selection = None
        artist_refs = {artist: ref for ref, artists in hits.items() for artist in artists}
        for artist in sorted([*axis.lines, *axis.patches, *axis.texts], key=lambda item: item.get_zorder()):
            self._insert(artist, artist_refs.get(artist))
        if self._fit or extent != old_extent:
            self.fit(self._focus_region)
        else:
            self._layout(center)
        if self._large_view is not None:
            self._large_view.set_scene(axis, hits, regions=regions)

    def show_large(self):
        """Open the current vector scene in a modeless, enlarged viewport."""
        if self._scene_source is None:
            return
        if self._large_view is not None:
            window = self._large_view.winfo_toplevel()
            window.deiconify()
            window.lift()
            return window

        window = Toplevel(self)
        window.title('电路大图')
        window.geometry('1120x740')
        window.minsize(480, 350)
        try:
            window.state('zoomed')
        except TclError:
            pass
        window.bind('<Escape>', lambda _event: window.destroy())

        def closed(event):
            if event.widget is window:
                self._large_view = None

        window.bind('<Destroy>', closed, add='+')
        self._large_view = view = TopologyCanvas(window, self._select_callback, fit_label=self._fit_label)
        view.pack(fill='both', expand=True, padx=6, pady=6)
        axis, hits, regions = self._scene_source
        view.set_scene(axis, hits, regions=regions)
        view.fit(self._focus_region or self._expand_region)
        view.highlight(self.selection)
        view.canvas.focus_set()
        return window

    @property
    def large_view_open(self):
        return self._large_view is not None

    def close_large(self):
        if self._large_view is not None:
            self._large_view.winfo_toplevel().destroy()

    def _xy(self, x, y):
        x_min, _, _, y_max = self._extent
        return ((x - x_min) * self.scale, (y_max - y) * self.scale)

    def _font(self, base, weight):
        key = (base, weight)
        if key not in self._fonts:
            self._fonts[key] = font.Font(root=self, family='Microsoft YaHei UI', weight=weight,
                                         size=self._size(base))
        return self._fonts[key]

    def _size(self, base):
        minimum = 7 if self.scale >= 7 else 5
        return -max(minimum, min(42, round(base * self.scale / 15)))

    def _insert(self, artist, ref):
        if not artist.get_visible():
            return
        c = self.canvas
        option = 'fill'
        if isinstance(artist, Line2D):
            points = artist.get_xydata()
            color = _color(artist.get_color())
            if len(points) == 1 and artist.get_marker() not in (None, 'None', '', ' '):
                x, y = self._xy(*points[0])
                radius = max(.045, artist.get_markersize() / 54) * self.scale
                option, color = 'outline', _color(artist.get_markeredgecolor())
                item = c.create_oval(x-radius, y-radius, x+radius, y+radius, tags='scene',
                                     outline=color, fill=_color(artist.get_markerfacecolor()))
            elif len(points) >= 2:
                coords = [value for point in points for value in self._xy(*point)]
                style = {'dash': (5, 4)} if artist.is_dashed() else {}
                item = c.create_line(*coords, fill=color, width=max(1, artist.get_linewidth()),
                                     capstyle='round', tags='scene', **style)
            else:
                return
        elif isinstance(artist, (Circle, Polygon)):
            option, color = 'outline', _color(artist.get_edgecolor())
            options = dict(fill=_color(artist.get_facecolor()), outline=color,
                           width=artist.get_linewidth(), tags='scene')
            if isinstance(artist, Circle):
                x, y = self._xy(*artist.center)
                r = artist.radius * self.scale
                item = c.create_oval(x-r, y-r, x+r, y+r, **options)
            else:
                coords = [value for point in artist.get_xy() for value in self._xy(*point)]
                item = c.create_polygon(*coords, **options)
        elif isinstance(artist, Text):
            if not artist.get_text():
                return
            h = {'left': 'w', 'right': 'e'}.get(artist.get_ha(), '')
            v = {'top': 'n', 'bottom': 's', 'baseline': 's'}.get(artist.get_va(), '')
            color = _color(artist.get_color())
            weight = 'bold' if artist.get_fontweight() in ('bold', 'semibold', 'heavy') else 'normal'
            base = artist.get_fontsize()
            caption_font = self._font(base, weight)
            item = c.create_text(*self._xy(*artist.get_position()), text=artist.get_text(),
                                 font=caption_font, fill=color, anchor=v+h or 'center', tags='scene')
        else:
            return
        if ref is not None:
            normal = {option: color}
            selected = {option: _SELECTED_INK}
            if isinstance(artist, Text):
                normal['font'] = caption_font
                selected['font'] = self._font(base, 'bold')
            else:
                width = float(c.itemcget(item, 'width'))
                normal['width'] = width
                selected['width'] = width + 1.3
            self._items[item] = ref
            self._refs.setdefault(ref, []).append((item, normal, selected))

    def highlight(self, ref):
        if self._large_view is not None:
            self._large_view.highlight(ref)
        if ref == self.selection:
            return
        for item, normal, _ in self._refs.get(self.selection, ()):
            self.canvas.itemconfigure(item, **normal)
        self.selection = ref if ref in self._refs else None
        for item, _, selected in self._refs.get(self.selection, ()):
            self.canvas.itemconfigure(item, **selected)

    def reveal(self, ref):
        self.highlight(ref)
        if ref not in self._refs:
            return
        c = self.canvas
        x, y = c.canvasx(0), c.canvasy(0)
        w, h = c.winfo_width(), c.winfo_height()
        boxes = [c.bbox(item) for item, _, _ in self._refs[ref]]
        if any(box and box[0] >= x and box[1] >= y and box[2] <= x+w and box[3] <= y+h for box in boxes):
            return
        first = next((box for box in boxes if box), None)
        if first:
            self._fit = False
            self._layout(((first[0]+first[2])/2, (first[1]+first[3])/2))

    def _fit_scale(self, region=None):
        x0, x1, y0, y1 = self._regions.get(region, self._extent)
        return min(max(30, self.canvas.winfo_width()-38) / (x1-x0),
                   max(30, self.canvas.winfo_height()-36) / (y1-y0), 72.)

    def _layout(self, center=None):
        if not self._extent:
            return
        c = self.canvas
        x0, x1, y0, y1 = self._extent
        width, height = (x1-x0)*self.scale, (y1-y0)*self.scale
        w, h = c.winfo_width(), c.winfo_height()
        c.configure(scrollregion=(-w, -h, width+w, height+h))
        if center is not None:
            c.xview_moveto((center[0] + w/2) / (width+2*w))
            c.yview_moveto((center[1] + h/2) / (height+2*h))
        self.zoom_text.set(f'{round(100*self.scale/self._fit_scale(self._focus_region))}%')

    def _scale_to(self, scale):
        ratio = scale / self.scale
        if abs(ratio - 1) < 1e-8:
            return
        self.canvas.scale('scene', 0, 0, ratio, ratio)
        self.scale = scale
        for (base, _), tk_font in self._fonts.items():
            tk_font.configure(size=self._size(base))

    def zoom(self, factor, x=None, y=None):
        if not self._extent:
            return 'break'
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        x = w/2 if x is None else x
        y = h/2 if y is None else y
        original = self.scale
        scene_x, scene_y = c.canvasx(x), c.canvasy(y)
        self._scale_to(min(180., max(self._fit_scale(self._focus_region)/4, original*factor)))
        ratio = self.scale / original
        self._fit = False
        self._layout((scene_x*ratio-x+w/2, scene_y*ratio-y+h/2))
        return 'break'

    def fit(self, region=None):
        if self._extent:
            self._fit = True
            self._focus_region = region
            self._scale_to(self._fit_scale(region))
            x0, x1, y0, y1 = self._regions.get(region, self._extent)
            self._layout(self._xy((x0+x1)/2, (y0+y1)/2))

    def _queue_layout(self, _event=None):
        if self._layout_job is None:
            self._layout_job = self._timer_owner.after_idle(self._resize)

    def _resize(self):
        self._layout_job = None
        if self._fit:
            self.fit(self._focus_region)
        else:
            self._layout()

    def _cancel_layout(self, _event=None):
        if self._layout_job is not None:
            self._timer_owner.after_cancel(self._layout_job)
            self._layout_job = None
        if self._grid_job is not None:
            self._timer_owner.after_cancel(self._grid_job)
            self._grid_job = None

    def _scroll(self, view, *args):
        self._fit = False
        view(*args)

    def _draw_grid(self):
        self._grid_job = None
        c = self.canvas
        step = 28
        left, top = int(c.canvasx(0)), int(c.canvasy(0))
        right, bottom = left+c.winfo_width(), top+c.winfo_height()
        c.delete('topology_grid')
        for x in range(left//step*step, right+step, step):
            c.create_line(x, top, x, bottom, fill='#e9eff6', tags='topology_grid')
        for y in range(top//step*step, bottom+step, step):
            c.create_line(left, y, right, y, fill='#e9eff6', tags='topology_grid')
        c.tag_lower('topology_grid')

    def _wheel(self, event):
        if event.delta:
            return self.zoom(1.18 if event.delta > 0 else 1/1.18, event.x, event.y)

    def _press(self, event):
        self.canvas.focus_set()
        self._drag_start = event.x, event.y
        self._dragged = False
        self.canvas.scan_mark(event.x, event.y)

    def _drag(self, event):
        if self._drag_start is None:
            return
        x, y = self._drag_start
        if self._dragged or max(abs(event.x-x), abs(event.y-y)) > 4:
            self._fit = False
            self._dragged = True
            self.canvas.configure(cursor='fleur')
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _release(self, event):
        c = self.canvas
        c.configure(cursor='')
        self._drag_start = None
        if event.num != 1 or self._dragged or self._select_callback is None:
            return
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        entries = [item for item in c.find_overlapping(x-5, y-5, x+5, y+5) if item in self._items]
        if entries:
            direct = set(c.find_overlapping(x, y, x, y))

            def rank(item):
                left, top, right, bottom = c.bbox(item)
                distance = (x-(left+right)/2)**2 + (y-(top+bottom)/2)**2
                return item not in direct, distance, c.type(item) != 'text'

            self._select_callback(self._items[min(entries, key=rank)])
