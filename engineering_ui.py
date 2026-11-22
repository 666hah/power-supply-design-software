"""Desktop parameter navigation, hardware tolerance and acceptance."""
import copy
import queue
import threading
import tkinter as tk
import weakref
from tkinter import ttk


class Tooltip:
    """One transient hint per owner, including delayed callbacks and cleanup."""
    def __init__(self, widget, text):
        self.widget, self.text, self.popup, self.job = widget, text, None, None
        self.owner = widget.winfo_toplevel()
        if not hasattr(self.owner, '_tooltip_instances'):
            self.owner._tooltip_instances = weakref.WeakSet()
            self.owner._active_tooltips = weakref.WeakSet()
            # Child bindtags include their toplevel: clicking/scrolling anywhere
            # in the window also dismisses a pending hint. Bind once per owner.
            for sequence in ('<ButtonPress>', '<MouseWheel>', '<FocusOut>', '<Unmap>', '<Configure>'):
                self.owner.bind(sequence, lambda _event: Tooltip.hide_all(self.owner), add='+')
        self.owner._tooltip_instances.add(self)
        widget.bind('<Enter>', self.enter, add='+')
        widget.bind('<Leave>', self.leave, add='+')
        widget.bind('<ButtonPress>', self.leave, add='+')
        widget.bind('<Unmap>', self.leave, add='+')
        widget.bind('<Destroy>', self.leave, add='+')

    @staticmethod
    def hide_all(owner):
        # Configure/Unmap fires for every field during reflow. Only pending or
        # visible hints need cleanup, not the entire parameter panel each time.
        for hint in tuple(getattr(owner, '_active_tooltips', ())):
            hint.leave()

    def enter(self, _event=None):
        Tooltip.hide_all(self.owner)
        try:
            if self.widget.winfo_exists() and self.widget.winfo_ismapped():
                self.job = self.widget.after(600, self.show)
                self.owner._active_tooltips.add(self)
        except tk.TclError:
            pass

    def _can_show(self):
        """A stale after must not display on another app or hidden control."""
        try:
            if not self.widget.winfo_exists() or not self.widget.winfo_viewable():
                return False
            if not self.owner.winfo_viewable():
                return False
            focused = self.owner.focus_displayof()
            if focused is None or focused.winfo_toplevel() is not self.owner:
                return False
            x, y = self.widget.winfo_pointerxy()
            target = self.owner.winfo_containing(x, y)
            while target is not None:
                if target is self.widget:
                    return True
                target = target.master
        except tk.TclError:
            pass
        return False

    def show(self):
        # Clear the previous callback/window before replacing any references.
        Tooltip.hide_all(self.owner)
        if not self._can_show():
            return
        try:
            self.popup = tk.Toplevel(self.owner)
            self.owner._active_tooltips.add(self)
            self.popup.withdraw()
            self.popup.wm_overrideredirect(True)
            self.popup.transient(self.owner)
            self.popup.geometry(f'+{self.widget.winfo_rootx()+12}+{self.widget.winfo_rooty()+28}')
            ttk.Label(self.popup, text=self.text, wraplength=440, padding=8,
                      background='#fff8e1', foreground='#22303c').pack()
            self.popup.deiconify()
        except tk.TclError:
            self.leave()

    def leave(self, _event=None):
        self.owner._active_tooltips.discard(self)
        job, self.job = self.job, None
        popup, self.popup = self.popup, None
        if job is not None:
            try:
                self.widget.after_cancel(job)
            except tk.TclError:
                pass
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass


class EngineeringUI:
    def _init_engineering_state(self):
        self._work_queue = queue.Queue()
        self._work_cancel = threading.Event()
        self._work_running = False
        self._work_poll = None

    def _build_param_filters(self, parent):
        self.left_canvas.bind('<Map>', self._schedule_parameter_scrollregion, add='+')
        frame = ttk.Frame(parent, style='WorkspaceToolbar.TFrame', padding=(4, 3, 4, 4))
        frame.pack(fill='x')
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='设计参数', style='WorkspaceHeading.TLabel').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        self.param_search = tk.StringVar()
        search = ttk.Entry(frame, textvariable=self.param_search, width=8)
        search.grid(row=1, column=0, sticky='ew', padx=(0, 6))
        Tooltip(search, '参数搜索。可输入中文名称、符号或字段名。')
        # Compatibility handle for older integrations/tests only. There is no
        # basic/advanced switch and this value no longer filters any inputs.
        self.advanced_params = tk.BooleanVar(value=True)
        ttk.Button(frame, text='展开全部', command=self._expand_params).grid(
            row=1, column=1, sticky='ew')
        ttk.Label(frame, text='搜索名称或符号', style='WorkspaceHint.TLabel').grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(5, 0))
        self.param_search.trace_add('write', lambda *_: self._filter_parameter_panel(refresh_rows=False))

    def _expand_params(self):
        self._cancel_parameter_scroll()
        folded = tuple(self._folded_sections)
        self._folded_sections.clear()
        if self.param_search.get():
            self.param_search.set('')
        elif folded:
            self._apply_parameter_folds(folded)

    def _fold_section(self, frame):
        self._cancel_parameter_scroll()
        if frame in self._folded_sections:
            self._folded_sections.remove(frame)
        else:
            self._folded_sections.add(frame)
        self._apply_parameter_folds((frame,))

    def _apply_parameter_folds(self, frames):
        Tooltip.hide_all(self.root)
        if self.param_search.get().strip():
            return
        for frame in frames:
            self._apply_parameter_section(frame)
        self._schedule_parameter_scrollregion()

    def _filter_params(self):
        if hasattr(self, 'param_search'):
            self._filter_parameter_panel()

    def _sync_parameter_scrollregion(self):
        self._param_layout_job = None
        if not getattr(self, '_closing', False) and not getattr(self,'_param_scroll_syncing',False):
            # The scheduled pass follows geometry notifications. Do not enter
            # a nested idle loop here: that also draws every pending figure and
            # starves input/timer events during a multi-output reflow.
            canvas=self.left_canvas
            if not self._parameter_pane_visible or not canvas.winfo_ismapped():
                return
            width=max(1,canvas.winfo_width())
            min_width = round(337 * self._font_k)
            content_width = max(width, min_width)
            self._resize_parameter_fields(content_width)
            if int(float(canvas.itemcget(self._param_canvas_window, 'width'))) != content_width:
                canvas.itemconfigure(self._param_canvas_window, width=content_width)
            hscroll = self._parameter_hscroll
            if content_width > width:
                if not hscroll.winfo_manager():
                    hscroll.pack(side='bottom', fill='x', before=canvas)
            elif hscroll.winfo_manager():
                hscroll.pack_forget()
                canvas.xview_moveto(0)
            height=max(self.left_inner.winfo_reqheight(),canvas.winfo_height())
            # A scroll region shorter than the viewport lets Tk retain a
            # negative origin after folding: the inputs then sit below a gap.
            region = (0, 0, content_width, height)
            if canvas.cget('scrollregion') != f'0 0 {content_width} {height}':
                canvas.configure(scrollregion=region)
            if canvas.canvasy(0) != 0 and (height == canvas.winfo_height() or canvas.canvasy(0) < 0):
                canvas.yview_moveto(0)
            requested = getattr(self, '_parameter_scroll_target', None)
            anchor = getattr(self, '_parameter_scroll_anchor', None)
            target = requested or anchor
            view_height = canvas.winfo_height()
            if target is not None and view_height > 4:
                if target.winfo_ismapped():
                    origin = self.left_inner.winfo_rooty()
                    top = target.winfo_rooty() - origin
                    if target is anchor:
                        bottom = top + target.winfo_height()
                        # Center the related rows that fit around the primary
                        # input. Far-away controls should not pull it offscreen.
                        for widget in self._parameter_scroll_context:
                            if widget.winfo_ismapped():
                                row_top = widget.winfo_rooty() - origin
                                start = min(top, row_top)
                                end = max(bottom, row_top + widget.winfo_height())
                                if end - start <= view_height:
                                    top, bottom = start, end
                        offset = (top + bottom - view_height) / 2
                    else:
                        offset = top - 4
                    offset = max(0, min(height - view_height, offset))
                    if abs(canvas.canvasy(0) - offset) > 1:
                        canvas.yview_moveto(offset / height)
                self._parameter_scroll_target = None

    def _cancel_parameter_scroll(self):
        """Release a located field's anchor when the user navigates the pane."""
        self._parameter_scroll_target = None
        self._set_parameter_scroll_anchor(None)

    def _set_parameter_scroll_anchor(self, widget, context=()):
        self._parameter_scroll_context = context
        previous = getattr(self, '_parameter_scroll_anchor', None)
        if previous is widget:
            return
        if previous is not None and previous.winfo_exists():
            previous.unbind('<Map>', self._parameter_scroll_map_binding)
        self._parameter_scroll_anchor = widget
        # The canvas can map before a nested field, with no subsequent
        # geometry change. Also request alignment when the actual field maps.
        self._parameter_scroll_map_binding = (widget.bind('<Map>', self._schedule_parameter_scrollregion, add='+')
                                              if widget is not None else None)

    def _schedule_parameter_scrollregion(self,_event=None):
        if not getattr(self,'_closing',False) and not getattr(self,'_param_scroll_syncing',False) and self._param_layout_job is None:
            # Nested pack requests may settle after the first idle callback;
            # an offscreen Canvas window then emits no Configure notification.
            self._param_layout_job=self.root.after(16,self._sync_parameter_scrollregion)

    def _tree(self, frame, columns, labels, widths=None, *, height=10):
        box = ttk.Frame(frame); box.pack(fill='both', expand=True, padx=6, pady=4)
        tree = ttk.Treeview(box, columns=columns, show='headings', height=height)
        for col,label,width in zip(columns,labels,widths or [120]*len(columns)):
            tree.heading(col,text=label)
            tree.column(col,width=width,minwidth=70,anchor='w')
        sy = ttk.Scrollbar(box,command=tree.yview); sy.pack(side='right',fill='y')
        sx = ttk.Scrollbar(box,orient='horizontal',command=tree.xview); sx.pack(side='bottom',fill='x')
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tree.pack(fill='both',expand=True)
        for tag,color in [('review','#b54708'),('undefined','#a83232'),('pass','#197442'),('na','#64748b')]:
            tree.tag_configure(tag,foreground=color)
        return tree

    def _build_tolerance_tab(self):
        from tolerance_ui import TolerancePanel

        self._tolerance_panel = TolerancePanel(
            self.tab_tolerance, get_spec=self._tolerance_spec, start=self._run_tolerances,
            cancel=self._work_cancel.set, make_tree=self._tree,
        )
        self._tolerance_panel.pack(fill='both', expand=True)

    def _build_review_tab(self):
        from engineering_acceptance_ui import AcceptancePanel

        self.acceptance_panel = AcceptancePanel(
            self.tab_review, get_spec=self._current_spec,
            on_apply=self._acceptance_apply,
            on_refresh=self._acceptance_refresh_endpoints,
            on_import_evidence=self._acceptance_import_evidence,
            get_range_result=self._acceptance_get_range_result,
            get_joint_record=self._acceptance_get_joint_record,
            get_spice_evidence=self._acceptance_get_spice_evidence,
        )
        self.acceptance_panel.pack(fill='both', expand=True)

    def _refresh_acceptance(self):
        self.acceptance_panel.refresh()

    def _current_spec(self):
        p = self.get_params()
        p.update(self._rcd_parameters())
        if hasattr(self, '_winding_config'):
            winding = self._winding_config().get('winding_config') or {}
            if winding.get('window_width', 0) > 0 and winding.get('window_height', 0) > 0:
                p['winding_config'] = copy.deepcopy(winding)
        return p

    def _invalidate_tolerance_result(self):
        if self._tolerance_panel.fingerprint is None:
            return
        try:
            current = self._tolerance_spec()
        except (ValueError, TypeError, KeyError, tk.TclError):
            current = None
        self._tolerance_panel.invalidate(current)

    def _tolerance_spec(self):
        return dict(self._current_spec(), __comp=self._comp_state())

    def _run_tolerances(self, spec, variables, settings, *, boundary_run=None):
        if self._work_running:
            return
        from time import monotonic
        from tolerance_analysis import analyze, resume_monte_carlo

        spec, variables, settings = copy.deepcopy((spec, variables, settings))
        self._tolerance_panel.started(spec, sampling=boundary_run is not None)
        self._work_cancel.clear()
        self._work_running = True
        messages, cancelled = self._work_queue, self._work_cancel.is_set

        def worker():
            last_update = -1.

            def report(done, total, label):
                nonlocal last_update
                now = monotonic()
                if done in (0, total) or now - last_update >= .08:
                    messages.put(('progress', (done, total, label)))
                    last_update = now

            try:
                if boundary_run is None:
                    result, plan = analyze(spec, variables, **settings, retain_plan=True,
                                           progress=report, cancelled=cancelled)
                    messages.put(('boundary', (result, plan)))
                else:
                    result = resume_monte_carlo(spec, *boundary_run, **settings,
                                                progress=report, cancelled=cancelled)
                    messages.put(('done', result))
            except Exception as exc:
                messages.put(('error', str(exc)))

        threading.Thread(target=worker, name='hardware-tolerance-analysis', daemon=True).start()

        def poll():
            self._work_poll = None
            if self._closing:
                return
            while True:
                try:
                    state, data = messages.get_nowait()
                except queue.Empty:
                    break
                if state == 'progress':
                    self._tolerance_panel.progress(*data)
                    continue
                self._work_running = False
                self._invalidate_tolerance_result()
                result = data[0] if state == 'boundary' else data if state == 'done' else None
                self._tolerance_panel.finished(
                    result=result,
                    boundary_run=data if state == 'boundary' else None,
                    error=data if state == 'error' else None,
                    cancelled=cancelled(),
                )
                return
            self._work_poll = self.root.after(80, poll)

        self._work_poll = self.root.after(80, poll)
