"""Desktop entry for field extraction from the current calculator unit."""
import copy
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_preferences import preferences_path


def _settings_file():
    return preferences_path().with_name('transformer-solver.json')


def _read_settings():
    try:
        data = json.loads(_settings_file().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(settings):
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _core_name(config):
    value = config.get('core_choice', '')
    return str(value.get('v', '') if isinstance(value, dict) else value)


def _matching_template(tool_root, core_name, settings):
    if not tool_root or not core_name:
        return ''
    root = Path(tool_root)
    templates = settings.get('templates', {})
    if settings.get('tool_root') == tool_root and isinstance(templates, dict):
        saved = templates.get(core_name)
        if isinstance(saved, str) and saved and Path(saved).is_file():
            return saved
    # Suggest only an unambiguous CAD model from the adjacent bounded project catalog.
    # The worker still validates the exact winding sections, material and geometry.
    catalog = root / '项目库'
    if not catalog.is_dir() and root.name == '变压器耦合参数提取工具':
        catalog = root.parent / '项目库'
    key = re.sub(r'[-_/\s]', '', core_name).casefold()
    if not key:
        return ''
    matches = []
    for project in catalog.glob('*/01_提取设置/提取设置.json'):
        try:
            data = json.loads(project.read_text(encoding='utf-8-sig'))
            core_file = Path(data['core']['path']).stem
        except (OSError, ValueError, KeyError, TypeError):
            continue
        compact = re.sub(r'[-_/\s]', '', core_file).casefold()
        if re.match(re.escape(key) + r'(?!\d)', compact):
            matches.append(project)
    return str(matches[0]) if len(matches) == 1 else ''


class _SimulationDialog:
    def __init__(self, app, config, *, container=None, settings_context=None, navigate=None):
        self.app = app
        self.settings_context = settings_context
        self.embedded = container is not None
        if self.embedded:
            self.win = container.winfo_toplevel()
        else:
            self.win = tk.Toplevel(app.root)
            self.win.title('变压器仿真与设计闭环')
            self.win.transient(app.root)
            self.win.grab_set()
        self.navigate = navigate
        win = self.win
        self.settings = _read_settings()
        self.core = _core_name(config)
        self.job = None
        self.closed = False
        previous = config.get('__transformer_simulation')
        self.result = previous if isinstance(previous, dict) else {}
        self.directory = self.result.get('directory')
        self.applied = True
        self.queue = queue.Queue()
        self.poll_id = None
        self.path_controls = []

        self.frame = frame = ttk.Frame(container if self.embedded else win, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)
        self.title = ttk.Label(frame, text=f'变压器电磁仿真 · {self.core or "自动选磁芯"}', font='TkHeadingFont')
        self.title.grid(
            row=0, columnspan=3, sticky='w', pady=(0, 6))
        self.status = tk.StringVar(win, '历史结果 · 可打开报告查看当时的磁件参数。' if self.result else
                                   '未运行 · 确认输入后可开始电磁仿真。')
        status = ttk.Label(frame, textvariable=self.status, style='ResultConclusion.TLabel',
                           wraplength=750, justify='left')
        status.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(0, 7))
        frame.bind('<Configure>', lambda event:status.configure(wraplength=max(250, event.width-30))
                   if event.widget is frame else None, add='+')
        self.output = tk.StringVar(win, self.settings.get('output_directory') or str(Path.home() / '变压器仿真报告'))
        if self.embedded:
            self._build_automatic_inputs(frame)
            rows = [(5, '报告保存目录', self.output, self.pick_output)]
        else:
            ttk.Label(frame, text='绕组几何取自当前设计。请核对提取设置中的磁芯、材料、坐标和接线。',
                      style='Muted.TLabel', wraplength=600).grid(row=3, columnspan=3, sticky='w', pady=(0, 8))
            root_path = self.settings.get('tool_root') or os.environ.get('POWER_DESIGN_TRANSFORMER_TOOL', '')
            self.tool = tk.StringVar(win, root_path)
            self.template = tk.StringVar(win, _matching_template(root_path, self.core, self.settings))
            rows = [(4, '本机提取工具目录', self.tool, self.pick_tool),
                    (5, '提取设置 JSON', self.template, self.pick_template),
                    (6, '报告保存目录', self.output, self.pick_output)]
        for row, label, var, pick in rows:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8))
            entry = ttk.Entry(frame, textvariable=var, width=50)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            button = ttk.Button(frame, text='选择…', command=pick)
            button.grid(row=row, column=2, padx=(6, 0))
            self.path_controls.extend((entry, button))
        self.log = tk.Text(frame, width=64, height=7, wrap='word', state='disabled',
                           font='TkDefaultFont')
        self.log.grid(row=7, column=0, columnspan=2, sticky='nsew', pady=(10, 6))
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.grid(row=7, column=2, sticky='nsw', pady=(10, 6))
        self.log.configure(yscrollcommand=scroll.set)
        bar = ttk.Frame(frame)
        bar.grid(row=2, columnspan=3, sticky='ew', pady=(0, 8))
        self.report = ttk.Button(bar, text='场仿真报告', command=lambda:self.open_report('report_path'))
        self.compare = ttk.Button(bar, text='闭环对比', command=lambda:self.open_report('comparison_path'))
        self.folder = ttk.Button(bar, text='运行目录', command=lambda:self.open_path(self.directory, directory=True))
        for btn in (self.report, self.compare, self.folder):
            btn.pack(side='left', padx=(0, 4))
        self.prepare = None
        if not self.embedded:
            self.prepare = ttk.Button(bar, text='从同型号磁芯准备参考设置…',
                                      command=lambda:self.start(prepare=True))
            self.prepare.pack(side='right')
        actions = ttk.Frame(frame)
        actions.grid(row=8, columnspan=3, sticky='ew', pady=(5, 0))
        self.apply = ttk.Button(actions, text='采用参数并重算', command=self.apply_result)
        self.stop = ttk.Button(actions, text='取消运行', command=self.cancel)
        self.run = ttk.Button(actions, text='开始电磁仿真' if self.embedded else '一键仿真并生成报告',
                              command=self.start)
        self.apply.pack(side='left')
        for btn in (self.run, self.stop):
            btn.pack(side='right', padx=(4, 0))
        self.refresh()
        if self.result:
            self.write('此单元已保存一次参数采用记录。可查阅当时的场仿真报告和闭环对比。')
            if self.result.get('project_file'):
                self.write('上次使用的提取设置：' + str(self.result['project_file']))
            if not self.embedded and not root_path and self.result.get('tool_root'):
                self.write('上次使用的工具目录：' + str(self.result['tool_root']) + '。请在本机重新选择。')
        elif not self.embedded:
            self.write('首次选择本机工具及提取设置后，后续可直接仿真。每次运行单独保存，完成后可核对结果再采用参数。')
        if self.embedded:
            self.write('本次任务的几何检查、求解进度与报告位置会显示在这里。')
            self.refresh_preflight(config)
        elif not all((config.get('winding_config') or {}).get(k) for k in ('window_width','window_height')):
            self.write('尚缺骨架净窗口尺寸。选好同型号模板后，可点击“从同型号磁芯准备参考设置…”预览参考排线和接线。')
        if not self.embedded:
            win.protocol('WM_DELETE_WINDOW', self.close)
        self.frame.bind('<Destroy>', self.destroyed, add='+')

    def _build_automatic_inputs(self, frame):
        card = ttk.LabelFrame(frame, text='模型与输入检查', padding=9)
        card.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        card.columnconfigure(0, weight=1)
        self.readiness = ttk.Label(card, text='未检查', wraplength=750, justify='left')
        self.readiness.grid(row=0, column=0, sticky='ew')
        if self.navigate is not None:
            ttk.Button(card, text='本机工具与磁芯模型…', command=lambda:self.navigate('tools')).grid(
                row=1, column=0, sticky='w', pady=(7, 0))
        def resize(event):
            self.readiness.configure(wraplength=max(250, event.width - 44))
        frame.bind('<Configure>', resize, add='+')

    def refresh_preflight(self, config):
        if not self.embedded or self.job is not None:
            return
        self.core = _core_name(config)
        self.title.configure(text=f'变压器电磁仿真 · {self.core or "自动选磁芯"}')
        try:
            readiness = self._automatic_inputs(config)
            has_elmer = self._has_elmer(readiness['environment'])
        except (ValueError, OSError, tk.TclError) as exc:
            self.readiness.configure(text=str(exc), foreground='#9a5809')
            return
        summary = readiness.get('summary') or '已有输入可用于准备本次电磁仿真。'
        missing = readiness.get('missing') or []
        if not has_elmer:
            missing = [*missing, '在本机工具中选择完整的 Elmer 安装目录。']
        if missing:
            summary = '待处理 · ' + ' '.join(missing) + '\n' + summary
            self.readiness.configure(text=summary, foreground='#9a5809')
        else:
            self.readiness.configure(text=summary, foreground='#24604b')

    def _snapshot_environment(self, config):
        if self.settings_context is None:
            raise ValueError('仿真环境尚未连接，请重新打开仿真配置中心。')
        self.settings_context.set_config(config)
        return self.settings_context.snapshot(require_spice=False)

    def _automatic_inputs(self, config):
        from portable_transformer_project import automatic_field_inputs
        return automatic_field_inputs(config, self._snapshot_environment(config))

    @staticmethod
    def _has_elmer(environment):
        from simulation_environment import normalize_elmer
        home = normalize_elmer(environment.get('elmer_home'))
        if not home:
            return False
        root = Path(home)
        return ((root / 'share/elmersolver/lib').is_dir() and all(
            (root / 'bin' / executable).is_file() for executable in ('ElmerSolver.exe', 'ElmerGrid.exe')))

    def pick_tool(self):
        path = filedialog.askdirectory(parent=self.win, title='选择寄生参数提取研究目录或提取工具目录')
        if path:
            self.tool.set(path)
            self.template.set(_matching_template(path, self.core, self.settings))

    def pick_template(self):
        catalog = Path(self.tool.get()) / '项目库'
        path = filedialog.askopenfilename(parent=self.win, title='选择匹配本变压器的提取设置',
                initialdir=str(catalog) if catalog.is_dir() else None, filetypes=[('提取设置', '*.json')])
        if path:
            self.template.set(path)

    def pick_output(self):
        path = filedialog.askdirectory(parent=self.win, title='选择报告保存目录')
        if path:
            self.output.set(path)

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', str(text).strip() + '\n')
        lines = int(self.log.index('end-1c').split('.')[0])
        if lines > 600:
            self.log.delete('1.0', f'{lines-500}.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh(self):
        busy = self.job is not None
        controls = [*self.path_controls, self.run]
        if self.prepare is not None:
            controls.append(self.prepare)
        for widget in controls:
            widget.state(['disabled'] if busy else ['!disabled'])
        self.stop.state(['!disabled'] if busy and not self.job.is_set() else ['disabled'])
        for button, key in ((self.report, 'report_path'), (self.compare, 'comparison_path')):
            button.state(['!disabled'] if self.result.get(key) and not busy else ['disabled'])
        self.folder.state(['!disabled'] if self.directory and not busy else ['disabled'])
        applicable = bool(self.result.get('proposed_config')) and not self.applied and not busy
        self.apply.state(['!disabled'] if applicable else ['disabled'])

    def start(self, *, prepare=False):
        if self.job is not None:
            return
        output = self.output.get().strip()
        if not output:
            self.status.set('未运行 · 请选择报告保存目录。')
            self.write(self.status.get())
            return
        try:
            config = copy.deepcopy(self.app._config_dict())
        except (ValueError, tk.TclError) as exc:
            self.status.set('未运行 · 请检查当前单元输入。' + str(exc))
            self.write(self.status.get())
            return

        run_inputs = {'output_directory': output}
        template = None
        if self.embedded:
            try:
                auto = self._automatic_inputs(config)
                if auto['missing']:
                    raise ValueError('；'.join(auto['missing']))
                if not self._has_elmer(auto['environment']):
                    raise ValueError('请在本机工具中选择完整的 Elmer 安装目录。')
            except (ValueError, OSError, tk.TclError) as exc:
                self.status.set('未运行 · ' + str(exc))
                self.write(self.status.get())
                self.refresh_preflight(config)
                return
            run_inputs['environment'] = copy.deepcopy(auto['environment'])
            self.settings = dict(_read_settings(), output_directory=output)
        else:
            tool, template = self.tool.get().strip(), self.template.get().strip()
            if not tool or not template or not Path(tool).is_dir() or not Path(template).is_file():
                self.status.set('未运行 · 请选择提取工具目录和提取设置 JSON。')
                self.write(self.status.get())
                return
            run_inputs.update(tool_root=tool, project_file=template)
            templates = dict(self.settings.get('templates') or {}) if self.settings.get('tool_root') == tool else {}
            templates[self.core] = template
            self.settings = dict(tool_root=tool, templates=templates, output_directory=output)
        try:
            _save_settings(self.settings)
        except OSError as exc:
            self.write('本次可以运行，本机路径设置保存失败：' + str(exc))
        self.job = cancel = threading.Event()
        if not prepare:
            self.result = {}
            self.directory = output
        self.refresh()
        if prepare:
            self.status.set('运行中 · 按当前匝数准备参考窗口、层序和接线。')
        else:
            self.status.set('运行中 · 正在同步绕组并检查仿真输入。')
        self.write(self.status.get())
        mailbox = self.queue
        def work():
            try:
                if prepare:
                    from transformer_sim_reference import prepare_reference
                    prepared = prepare_reference(config, project_file=template, output_directory=output,
                                                 cancelled=cancel.is_set)
                    mailbox.put(('reference', (prepared, config)))
                    return
                from transformer_simulation import run_transformer_simulation
                result = run_transformer_simulation(config, **run_inputs, cancelled=cancel.is_set,
                    progress=lambda message:mailbox.put(('progress', message)))
                mailbox.put(('done', result))
            except Exception as exc:
                mailbox.put(('error', (str(exc) or type(exc).__name__, getattr(exc, 'directory', None))))
        threading.Thread(target=work, name='transformer-field-report', daemon=True).start()
        self.poll_id = self.win.after(80, self.poll)

    def poll(self):
        self.poll_id = None
        if self.closed:
            return
        for _ in range(60):
            try:
                kind, data = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == 'progress':
                self.status.set('运行中 · ' + str(data))
                self.write(data)
                continue
            cancelled = self.job is not None and self.job.is_set()
            self.job = None
            if kind == 'error' and data[1]:
                self.directory = data[1]
            if cancelled and kind in ('error','reference'):
                self.status.set('已取消 · 已有记录可在运行目录查看。')
                self.write(self.status.get())
            elif kind == 'error':
                self.status.set('失败 · ' + data[0])
                self.write(self.status.get())
                if not self.embedded:
                    self.write('如缺少窗口、层序或接线与模板不符，可从同型号磁芯准备参考设置，核对后重新仿真。')
            elif kind == 'reference':
                self.adopt_reference(*data)
            else:
                self.result = data
                self.applied = False
                self.directory = data['directory']
                if data.get('preparation'):
                    self.write(data['preparation'])
                field = data.get('record', {}).get('field', {})
                conclusion = '已完成 · 电磁仿真与对比报告已生成。'
                if 'primary_self_H' in field and 'primary_short_H' in field:
                    conclusion = '已完成 · 原边开路自感 %.4g µH · 全部副边短路时的原边漏感 %.4g µH' % (
                        field['primary_self_H'] * 1e6, field['primary_short_H'] * 1e6)
                for note in data.get('notes') or []:
                    self.write(note)
                self.status.set(conclusion)
                self.write(self.status.get())
            if self.directory:
                self.write('运行文件位置：' + str(self.directory))
            self.refresh()
            return
        if self.job is not None:
            self.poll_id = self.win.after(100, self.poll)

    def adopt_reference(self, prepared, original_config):
        summary = str(prepared['summary'])
        self.write(summary)
        self.write('生成的参考设置：' + str(prepared['project_file']))
        if not messagebox.askyesno('采用参考绕制与建模设置', summary +
                '\n\n请核对骨架窗口、每层绕组和匝数、材料、气隙，以及各段同向串联的假设。'
                '\n是否将上面的参考设置写入当前单元，作为这次仿真的输入？',
                default='no', parent=self.win):
            self.status.set('参考设置已生成，尚未采用。')
            self.write(self.status.get())
            return
        try:
            if self.app._config_dict() != original_config:
                raise ValueError('准备参考设置后设计参数已变化，请重新准备。')
            self.app._apply_config(prepared['config'])
        except (ValueError, OSError, KeyError, tk.TclError) as exc:
            self.status.set('无法采用参考设置：' + str(exc))
            self.write(self.status.get())
            return
        self.result = {}
        self.applied = True
        self.template.set(str(prepared['project_file']))
        self.directory = str(Path(prepared['project_file']).parent)
        self.status.set('参考设置已采用，可按当前单元开始电磁仿真。')
        self.write(self.status.get())
        self.app.status_var.set('参考绕制与建模设置已应用，可运行场解或返回画布保存工程。')

    def cancel(self):
        if self.job is not None:
            self.job.set()
            self.status.set('正在取消 · 等待当前求解停止。')
            self.write(self.status.get())
            self.refresh()

    def open_report(self, key):
        self.open_path(self.result.get(key))

    def open_path(self, value, *, directory=False):
        path = Path(value or '')
        if not path.is_absolute() or path.drive.startswith('\\\\'):
            self.write('请选择本机磁盘上的报告或运行目录。')
            return
        if not (path.is_dir() if directory else path.suffix.lower() in ('.html', '.pdf') and path.is_file()):
            self.write('找不到本地报告或运行目录：' + str(path))
            return
        try:
            os.startfile(str(path.resolve()))
        except OSError as exc:
            self.write('打开报告失败：' + str(exc))

    def apply_result(self):
        if self.applied or not self.result.get('proposed_config'):
            return
        if not messagebox.askyesno('采用场解参数',
                '将闭环对比中的候选参数写入当前单元并重新计算？\n返回画布后，点击“保存系统工程”可保存到文件。',
                parent=self.win):
            return
        try:
            from transformer_simulation import apply_transformer_simulation
            config = apply_transformer_simulation(self.app._config_dict(), self.result)
            self.app._apply_config(config)
        except (ValueError, OSError, KeyError, tk.TclError) as exc:
            self.write('无法采用本次结果：' + str(exc))
            return
        self.applied = True
        self.refresh()
        self.status.set('已采用 · 当前单元正在按场解参数重算。')
        self.write(self.status.get())
        self.app.status_var.set('变压器仿真参数已采用，可返回画布并保存系统工程。')

    def close(self):
        if self.job is not None:
            self.cancel()
            return
        (self.frame if self.embedded else self.win).destroy()

    def destroyed(self, event):
        if event.widget is self.frame:
            self.closed = True
            if self.job is not None:
                self.job.set()
            if self.poll_id is not None:
                try:
                    self.win.after_cancel(self.poll_id)
                except tk.TclError:
                    pass
                self.poll_id = None


def show(app):
    try:
        config = app._config_dict()
    except (ValueError, tk.TclError) as exc:
        messagebox.showerror('请检查当前单元输入', str(exc), parent=app.root)
        return None
    return _SimulationDialog(app, config).win
