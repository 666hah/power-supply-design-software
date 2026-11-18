"""Modeless architecture diagrams and offline tutorials for the desktop app."""

import tkinter as tk
from tkinter import ttk


PAGES_LABELS = (
    ('overview', '功能总览'),
    ('workflow', '设计与验证流程'),
    ('structure', '计算与交付结构'),
)

_FONT = 'Microsoft YaHei UI'
_NAVY = '#112a46'
_INK = '#172e48'
_MUTED = '#4b6279'
_BG = '#f4f7fb'
_WHITE = '#ffffff'
_LINE = '#dae4ef'
_COLORS = {
    'blue': ('#1b61b5', '#eaf3ff', '#b8d3f2'),
    'teal': ('#107771', '#e5f5f2', '#afdcd3'),
    'violet': ('#624ba2', '#f1edfb', '#d2c6eb'),
    'amber': ('#875322', '#fcf1e4', '#ead2b7'),
    'neutral': ('#496782', '#eef3f8', '#c7d5e3'),
}


def add_architecture_menu(menubar, parent):
    menu = tk.Menu(menubar, tearoff=False)
    for page, label in PAGES_LABELS:
        menu.add_command(label=label, command=lambda key=page: open_architecture(parent, key))
    menu.add_separator()
    menu.add_command(label='操作教程目录', command=lambda: _open_tutorial('index', parent))
    menubar.add_cascade(label='功能架构', menu=menu)


def _open_tutorial(topic, parent):
    from software_architecture_help import open_architecture_tutorial
    open_architecture_tutorial(topic, parent)


def open_architecture(parent, page='overview'):
    app_root = parent._root()
    viewer = getattr(app_root, '_architecture_viewer', None)
    if viewer is None or not viewer.winfo_exists():
        viewer = ArchitectureViewer(app_root)
        app_root._architecture_viewer = viewer
    viewer.show_page(page)
    viewer.deiconify()
    viewer.lift()
    viewer.focus_set()
    return viewer


class ArchitectureViewer(tk.Toplevel):
    def __init__(self, parent):
        from software_architecture_data import PAGES, TOPICS

        super().__init__(parent)
        self.pages = PAGES
        self.topics = TOPICS
        self.page = None
        self.zoom = None
        self._draw_job = None
        self._card_items = {}
        self.title('开关电源设计 · 功能架构')
        self.configure(bg=_BG)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(round(screen_width * .94), screen_width - 24)
        height = min(round(screen_height * .92), screen_height - 90)
        self.geometry(f'{width}x{height}+{(screen_width-width)//2}+{max(4, (screen_height-height)//5)}')
        self.minsize(min(620, width), min(450, height))
        self.bind('<Escape>', lambda _event: self.destroy())
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        style = ttk.Style(self)
        style.configure('Architecture.TButton', padding=(11, 6),
                        font=(_FONT, -13), foreground=_INK)
        style.configure('ArchitectureTab.Toolbutton', padding=(16, 5),
                        font=(_FONT, -15, 'bold'), background=_BG,
                        foreground=_MUTED, borderwidth=0)
        style.map('ArchitectureTab.Toolbutton',
                  background=[('selected', '#e3eefc'), ('active', '#eaf1f8')],
                  foreground=[('selected', '#174f90'), ('active', _INK)])

        header = tk.Frame(self, bg=_NAVY)
        header.grid(row=0, column=0, sticky='ew')
        tk.Label(header, text='软件功能架构', bg=_NAVY, fg=_WHITE,
                 font=(_FONT, -22, 'bold')).pack(anchor='w', padx=24, pady=8)

        nav = tk.Frame(self, bg=_BG)
        nav.grid(row=1, column=0, sticky='ew', padx=18, pady=(5, 2))
        self.selection = tk.StringVar(self)
        for key, title in PAGES_LABELS:
            ttk.Radiobutton(nav, text=title, value=key, variable=self.selection,
                            style='ArchitectureTab.Toolbutton',
                            command=lambda selected=key: self.show_page(selected)).pack(side='left', padx=(0, 4))

        self.intro = tk.Label(self, bg=_BG, fg=_MUTED, font=(_FONT, -14),
                              anchor='w', justify='left')
        self.intro.grid(row=2, column=0, sticky='ew', padx=24, pady=(1, 5))
        self.intro.bind('<Configure>', self._wrap_description)

        content = tk.Frame(self, bg=_BG)
        content.grid(row=3, column=0, sticky='nsew', padx=18)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(content, bg=_WHITE, bd=0, highlightthickness=1,
                                highlightbackground=_LINE, xscrollincrement=18, yscrollincrement=18)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(content, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(content, orient='horizontal', command=self.canvas.xview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.bind('<Configure>', self._schedule_draw)
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Button-4>', self._wheel)
        self.canvas.bind('<Button-5>', self._wheel)
        self.canvas.bind('<ButtonPress-1>', lambda event: self.canvas.focus_set())
        self.canvas.bind('<ButtonRelease-1>', self._click_card)
        self.canvas.bind('<Motion>', self._hover_card)
        self.canvas.bind('<Leave>', lambda _event: self.canvas.configure(cursor=''))
        self.canvas.bind('<Up>', lambda _event: self.canvas.yview_scroll(-2, 'units'))
        self.canvas.bind('<Down>', lambda _event: self.canvas.yview_scroll(2, 'units'))
        self.canvas.bind('<Left>', lambda _event: self.canvas.xview_scroll(-2, 'units'))
        self.canvas.bind('<Right>', lambda _event: self.canvas.xview_scroll(2, 'units'))

        footer = tk.Frame(self, bg=_BG)
        footer.grid(row=4, column=0, sticky='ew', padx=20, pady=(4, 2))
        zoom_bar = tk.Frame(footer, bg=_BG)
        zoom_bar.pack(side='right')
        self.footer = tk.Label(self, bg=_BG, fg=_MUTED, font=(_FONT, -12),
                               anchor='w', justify='left')
        self.footer.grid(row=5, column=0, sticky='ew', padx=24, pady=(0, 4))
        self.footer.bind('<Configure>', self._wrap_description)
        self.zoom_text = tk.StringVar(self)
        for title, command in (('−', lambda: self._change_zoom(-.15)),
                               ('+', lambda: self._change_zoom(.15)),
                               ('适合窗口', self._fit)):
            ttk.Button(zoom_bar, text=title, command=command, width=3 if len(title) == 1 else 9,
                       style='Architecture.TButton').pack(side='left', padx=2)
            if title == '−':
                tk.Label(zoom_bar, bg=_BG, fg=_INK, width=6, textvariable=self.zoom_text,
                         font=(_FONT, -13)).pack(side='left')

        access = tk.Frame(footer, bg=_BG)
        access.pack(side='left', fill='x', expand=True, padx=(4, 0))
        tk.Label(access, text='操作教程', bg=_BG, fg=_INK,
                 font=(_FONT, -13, 'bold')).pack(side='left', padx=(0, 8))
        self.lesson = ttk.Combobox(access, state='readonly', font=(_FONT, -13), width=17)
        self.lesson.pack(side='left', padx=(0, 8))
        self.lesson.bind('<Return>', self._open_selected)
        self.lesson.bind('<KP_Enter>', self._open_selected)
        ttk.Button(access, text='打开所选教程', command=self._open_selected,
                   style='Architecture.TButton').pack(side='left', padx=(0, 8))
        ttk.Button(access, text='教程目录', command=lambda: _open_tutorial('index', self),
                   style='Architecture.TButton').pack(side='left')

    @staticmethod
    def _wrap_description(event):
        if event.width > 1 and event.widget.cget('wraplength') != event.width:
            event.widget.configure(wraplength=event.width)

    def show_page(self, key):
        if self.page is self.pages[key]:
            return
        self.page = self.pages[key]
        self.title(f"软件功能架构 · {self.page['title']}")
        self.selection.set(key)
        self.intro.configure(text=self.page['intro'])
        self.footer.configure(text=self.page.get('footer', ''))
        self.footer.grid() if self.page.get('footer') else self.footer.grid_remove()
        self.lesson['values'] = [node[6] for node in self.page['nodes']]
        self.lesson.current(0)
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._schedule_draw()

    def _fit(self):
        self.zoom = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._schedule_draw()

    def _scale(self):
        width, height = self.page.get('size', (1100, 730))
        fit = min((self.canvas.winfo_width()-30) / width, (self.canvas.winfo_height()-26) / height)
        return self.zoom or max(.52, min(1.7, fit))

    def _change_zoom(self, delta):
        self.zoom = max(.52, min(2.0, self._scale() + delta))
        self._schedule_draw()

    def _wheel(self, event):
        delta = 120 if event.num == 4 else -120 if event.num == 5 else event.delta
        if delta:
            if event.state & 0x4:
                self._change_zoom(.1 if delta > 0 else -.1)
            else:
                scroll = self.canvas.xview_scroll if event.state & 0x1 else self.canvas.yview_scroll
                scroll(-int(delta / 120 * 3) or (-1 if delta > 0 else 1), 'units')
        return 'break'

    def _schedule_draw(self, _event=None):
        if self._draw_job is None and self.page is not None:
            self._draw_job = self.after_idle(self._draw)

    def _open_card(self, index):
        self.lesson.current(index)
        node = self.page['nodes'][index]
        _open_tutorial(self.topics[node[0]], self)

    def _open_selected(self, _event=None):
        index = self.lesson.current()
        if index >= 0:
            self._open_card(index)
        return 'break'

    def _card_at_event(self, event):
        items = self.canvas.find_overlapping(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y),
                                             self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        return next((self._card_items[item] for item in reversed(items) if item in self._card_items), None)

    def _click_card(self, event):
        index = self._card_at_event(event)
        if index is not None:
            self._open_card(index)

    def _hover_card(self, event):
        index = self._card_at_event(event)
        self.canvas.configure(cursor='hand2' if index is not None else '')

    def destroy(self):
        if self._draw_job is not None:
            self.after_cancel(self._draw_job)
            self._draw_job = None
        super().destroy()

    def _draw(self):
        self._draw_job = None
        canvas, page, scale = self.canvas, self.page, self._scale()
        width, height = page.get('size', (1100, 730))
        view_width, view_height = canvas.winfo_width(), canvas.winfo_height()
        offset = max(14, (view_width - width * scale)/2)

        def coord(x, y):
            return offset + x*scale, 12 + y*scale

        def text(x, y, value, *, color, size, bold=False, limit=None, tags=()):
            canvas.create_text(*coord(x, y), text=value, anchor='nw', fill=color,
                               width=0 if limit is None else round(limit*scale), justify='left',
                               font=(_FONT, -round(size*scale), 'bold' if bold else 'normal'), tags=tags)

        def rounded(x, y, w, h, radius, *, fill, outline, tags=()):
            x1, y1 = coord(x, y)
            x2, y2 = coord(x+w, y+h)
            r = radius*scale
            canvas.create_polygon(x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
                                  x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
                                  x1, y2, x1, y2-r, x1, y1+r, x1, y1,
                                  smooth=True, fill=fill, outline=outline, width=1, tags=tags)

        self.zoom_text.set(f'{round(scale*100)}%')
        canvas.delete('all')
        self._card_items.clear()
        canvas.configure(cursor='')
        canvas.configure(scrollregion=(0, 0, max(view_width-2, width*scale+28),
                                       max(view_height-2, height*scale+24)))
        for y, lane_height, label in page['lanes']:
            rounded(0, y, width, lane_height, 12, fill='#f5f8fc', outline='#e1e9f3')
            text(18, y+10, label, color=_MUTED, size=14, bold=True, tags=('lane-title',))

        for role, points in page['edges']:
            positions = [v for point in points for v in coord(*point)]
            adoption = role == 'adoption'
            accent = _COLORS['amber' if adoption else role][0]
            canvas.create_line(*positions, width=max(1.25, 1.75*scale), fill=accent,
                               arrow='last', arrowshape=tuple(s*scale for s in (8, 10, 4)),
                               joinstyle='round', dash=(6, 4) if adoption else (), tags=('connector',))

        for role, x, y, label in page.get('labels', ()):
            text(x, y, label, color=_COLORS[role][0], size=13, tags=('connector-label',))

        for index, (key, x, y, w, h, role, title, body) in enumerate(page['nodes']):
            accent, fill, outline = _COLORS[role]
            tag = f'lesson-{key}'
            rounded(x, y, w, h, 10, fill=fill, outline=outline, tags=('node', f'card-{key}', tag))
            canvas.create_line(*coord(x+1, y+14), *coord(x+1, y+h-14),
                               fill=accent, width=max(2, 3*scale), capstyle='round', tags=(tag,))
            text(x+15, y+9, title, color=_INK, size=18, bold=True,
                 limit=w-30, tags=(f'title-{key}', tag))
            text(x+15, y+37, body, color=_MUTED, size=14,
                 limit=w-30, tags=(f'body-{key}', tag))
            text(x+w-58, y+h-17, '教程  ↗', color=accent, size=12, bold=True, tags=(f'link-{key}', tag))
            self._card_items.update(dict.fromkeys(canvas.find_withtag(tag), index))
