"""Desktop specification-to-design preview. All Tk access stays on the UI thread."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from design_engine.initial_design import describe, form_options, generate


LLC_BRIDGES = {'半桥': 1., '全桥': 2.}


def show(app):
    from calculation_scheduler import CalculationCancelled
    try:
        options = form_options(app._config_dict()) if app._topo_key() in ('BUCK','BOOST','FLYBACK','LLC') else form_options()
    except (ValueError, KeyError, tk.TclError):
        options = form_options()
    win = tk.Toplevel(app.root)
    win.title('生成电源设计初版')
    win.transient(app.root)
    win.grab_set()
    panel = ttk.Frame(win,padding=12)
    panel.pack(fill='both',expand=True)
    panel.columnconfigure(1,weight=1)
    panel.columnconfigure(3,weight=1)
    conclusion = tk.StringVar(win)
    ttk.Label(panel, textvariable=conclusion, style='ResultConclusion.TLabel', wraplength=620,
              justify='left').grid(row=0, columnspan=4, sticky='ew')
    ttk.Label(panel, text='查看校核结果后，可将初版应用到当前单元。').grid(
        row=1, columnspan=4, sticky='w', pady=(2, 8))
    variants=options['variants']
    topology=tk.StringVar(win,options['topology'])
    mode=tk.StringVar(win)
    conduction=tk.StringVar(win)
    ttk.Label(panel,text='拓扑').grid(row=2,column=0,sticky='w')
    topology_box=ttk.Combobox(panel,textvariable=topology,values=list(variants),state='readonly',width=9)
    topology_box.grid(row=2,column=1,sticky='ew',padx=(0,10))
    controller_label = ttk.Label(panel,text='控制器参考')
    controller_label.grid(row=2,column=2,sticky='w')
    controller=ttk.Combobox(panel,textvariable=mode,state='readonly')
    controller.grid(row=2,column=3,sticky='ew')
    form=ttk.Frame(panel)
    form.grid(row=3,columnspan=4,sticky='ew',pady=4)
    form.columnconfigure(1,weight=1)
    form.columnconfigure(3,weight=1)
    entries = {}
    locks = {}
    ratio_widgets=[]
    lock_row = ttk.Frame(panel)
    lock_row.grid(row=4,columnspan=4,sticky='w',pady=5)
    names = dict(L='锁定 L',inductor_dcr='锁定 DCR',input_capacitors='锁定输入电容组',
                 output_capacitors='锁定输出电容组',rail_banks='锁定各路输出电容组',
                 llc_lr='锁定 Lr',llc_cr='锁定 Cr',llc_lm='锁定 Lm')
    output = tk.Text(panel,height=10,width=73,wrap='word',font='TkDefaultFont',state='disabled')
    output.grid(row=5,columnspan=4,sticky='nsew')
    scroll = ttk.Scrollbar(panel,orient='vertical',command=output.yview)
    scroll.grid(row=5,column=4,sticky='ns')
    output.configure(yscrollcommand=scroll.set)
    panel.rowconfigure(5,weight=1)
    bar = ttk.Frame(panel)
    bar.grid(row=6,columnspan=4,sticky='ew',pady=(8,0))
    mailbox = queue.Queue()
    stop = threading.Event()
    active_job = None
    candidate = None
    revision = 0

    def display(text):
        heading, _, details = text.partition('\n')
        conclusion.set(heading)
        output.configure(state='normal')
        output.delete('1.0','end')
        output.insert('1.0',details)
        output.configure(state='disabled')

    def invalidate(*_):
        nonlocal candidate,revision
        revision += 1
        if active_job is not None:
            active_job.set()
        candidate = None
        apply_button.state(['disabled'])
        display('规格有修改，待重新校核\n点击「生成并校核」更新预览。')

    def close():
        stop.set()
        win.destroy()

    def update_conduction(*_):
        for widget in ratio_widgets:
            if conduction.get()=='DCM': widget.grid_remove()
            else: widget.grid()
        invalidate()

    def switch_topology(*_):
        selected=topology.get()
        choice=variants[selected]
        ratio_widgets.clear()
        for frame in (form,lock_row):
            for widget in frame.winfo_children():
                widget.destroy()
        entries.clear()
        locks.clear()
        controller.configure(values=list(choice['modes'].values()))
        controller_label.configure(text='控制方式' if selected=='LLC' else '控制器参考')
        mode.set(choice['modes'][choice['mode']])
        for i,(key,label,_,_) in enumerate(choice['fields']):
            row,col=divmod(i,2)
            col*=2
            caption=ttk.Label(form,text='原边桥式' if key=='bridge' else label)
            caption.grid(row=row,column=col,sticky='w',padx=(4,5),pady=3)
            v=choice['values'][key]
            if key=='bridge':
                bridge = next(label for label, value in LLC_BRIDGES.items() if value==v)
                entries[key]=tk.StringVar(win,bridge)
                editor=ttk.Combobox(form,textvariable=entries[key],values=tuple(LLC_BRIDGES),
                                    state='readonly',width=10)
            else:
                entries[key]=tk.StringVar(win,'' if v is None else f"{v:g}")
                editor=ttk.Entry(form,textvariable=entries[key],width=10,
                                 state='readonly' if key=='fs' and 'conduction' in choice else 'normal')
            editor.grid(row=row,column=col+1,sticky='ew')
            if key=='il_ratio' and 'conduction' in choice: ratio_widgets.extend((caption,editor))
            entries[key].trace_add('write',invalidate)
        if 'conduction' in choice:
            row=(len(choice['fields'])+1)//2
            ttk.Label(form,text='额定负载导通模式').grid(row=row,column=0,sticky='w')
            conduction.set(choice['conduction'])
            ttk.Combobox(form,textvariable=conduction,values=('CCM','DCM'),state='readonly',width=9).grid(row=row,column=1,sticky='w')
            ttk.Label(form,text=choice['hint'],wraplength=600).grid(row=row+1,columnspan=4,sticky='w')
        for index, key in enumerate(choice['locks']):
            locks[key]=tk.BooleanVar(win)
            lock = ttk.Checkbutton(lock_row,text=names[key],variable=locks[key])
            if selected=='LLC':
                row,col=divmod(index,3)
                lock.grid(row=row,column=col,sticky='w',padx=(0,9))
            else:
                lock.pack(side='left')
            locks[key].trace_add('write',invalidate)

    def apply():
        if candidate is not None:
            app._apply_config(candidate)
            app.status_var.set(f"已采用 {candidate['topology']} 初版。可继续调整并保存工程。")
            close()

    def start():
        nonlocal candidate,active_job
        candidate = None
        apply_button.state(['disabled'])
        try:
            choice=variants[topology.get()]
            def value(k, scale):
                text = entries[k].get().strip()
                if not text:
                    return None
                return (LLC_BRIDGES[text] if k=='bridge' else float(text)) * scale

            request = {k:value(k, scale)
                       for k,_,scale,_ in choice['fields']
                       if not (k=='il_ratio' and 'conduction' in choice and conduction.get()=='DCM')}
            request.update(topology=topology.get(),control_mode=next(k for k,v in choice['modes'].items() if v==mode.get()),
                           locked={k:choice['locks'][k] for k,v in locks.items() if v.get()})
            if 'conduction' in choice:
                request.update(conduction=conduction.get(),windings=choice.get('windings',{}))
        except (ValueError, KeyError):
            display('规格待修正\n请填写有效数字。最小负载电流可留空。')
            return
        ticket = revision
        active_job = threading.Event()
        cancel_job = active_job
        generate_button.state(['disabled'])
        display('正在生成与校核…\n正在选取器件参数并复算各输入与负载工况。')
        def work():
            try:
                result = generate(request,cancelled=lambda:stop.is_set() or cancel_job.is_set())
                mailbox.put((result,describe(result)))
            except CalculationCancelled:
                mailbox.put((None,'规格有修改，待重新校核\n点击「生成并校核」更新预览。'))
            except Exception as exc:
                mailbox.put((None,'未能生成初版\n'+str(exc)))

        def poll():
            nonlocal candidate,active_job
            try:
                result,note = mailbox.get_nowait()
            except queue.Empty:
                if not stop.is_set():
                    win.after(65,poll)
                return
            generate_button.state(['!disabled'])
            active_job=None
            if ticket == revision:
                candidate = result
                display(note)
                if result is not None:
                    apply_button.state(['!disabled'])
        threading.Thread(target=work,daemon=True).start()
        win.after(65,poll)

    ttk.Button(bar,text='查看选值依据',command=app.open_auto_design_basis).pack(side='left')
    ttk.Button(bar,text='关闭',command=close).pack(side='right')
    apply_button = ttk.Button(bar,text='采用此初版',command=apply,state='disabled')
    apply_button.pack(side='right',padx=5)
    generate_button = ttk.Button(bar,text='生成并校核',command=start)
    generate_button.pack(side='right')
    mode.trace_add('write',invalidate)
    conduction.trace_add('write',update_conduction)
    topology.trace_add('write',switch_topology)
    switch_topology()
    win.protocol('WM_DELETE_WINDOW',close)
    win.bind('<Escape>',lambda _e:close())
    display('待生成初版\n填写输入电压范围、负载和纹波目标。选择与当前工程相同的拓扑可锁定已有器件。')
    return win
