"""Grouped controller settings and owned simulation/comparison operations."""
import copy
from concurrent.futures import ThreadPoolExecutor
from tkinter import font as tkfont
import threading
import time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from spice_export import SETTINGS,CHOICES,setting_group,ordered_setting_keys,normalize_settings,mp6005_preset,export_project


def _choice_labels(key):
    from controller_logic import SHORT_CHOICES
    short = {
        'niso_profile': {0:'未启用',1:'TPS40200',2:'LTC3864',3:'LM5022'},
        'niso_edge_model': {0:'快速闭环',1:'常数 Coss / Cj'},
        'cross_mode': {0:'智能角点',1:'全量角点'},
        'simulation_reuse': {0:'重新运行',1:'复用有效结果'},
    }.get(key, SHORT_CHOICES.get(key, {}))
    return {number:f'{number} · {short.get(number,label)}' for number,label in CHOICES[key].items()}


def comparison_feedback(result):
    """A diagnostic report is not a successfully simulated comparison."""
    counts=(f"瞬态完成 {result['successful']}/{result['total']}；"
        f"有效 FRA {result['fra_successful']}/{result['fra_total']}；"
        f"完整交叉调整率 {result['cross_successful']}/{result['cross_total']}。\n")
    if result.get('cached_nominal'):counts+=f"其中 {result['cached_nominal']} 个标称工况复用已有有效结果。\n"
    if not result['successful']:
        return 'warning','仿真未完成','所有工况均未完成，已保存诊断报告与工程 ZIP。\n'+counts+'报告中没有有效仿真对比数据，请查看各工况日志与失败原因。\n'
    if result['incomplete']:
        return 'warning','对比部分完成','已保存报告与同名工程 ZIP。\n'+counts+'存在未完成或待复核项目，请查看报告状态和原因。\n'
    return 'info','对比已完成','Word 报告与同名仿真工程 ZIP 已输出。\n'+counts


def supports_design(parameters):
    return (parameters.get('topology') in ('FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST')
            and parameters.get('feedback_mode','SSR') == 'SSR')


def open_export_dialog(parent,parameters,apply_settings,*,get_parameters=None,initial_tab=None,
                       container=None,settings_context=None,navigate=None):
    qr=parameters.get('topology')=='QR-FLYBACK'
    forward=parameters.get('topology')=='ACF-FORWARD'
    from cot_settings import active as cot_active
    cot=cot_active(parameters)
    noniso=parameters.get('topology') in ('BUCK','BOOST') and not cot
    from nonisolated import profile,preset,is_enabled,reference_settings
    if noniso and not is_enabled(parameters):
        parameters=copy.deepcopy(parameters)
        parameters['spice_config']=preset(profile(parameters)['id'])
    from acf_spice import preset as acf_preset
    from qr_spice_settings import applicable_keys,l6565_preset
    keys=applicable_keys(parameters.get('topology'))
    if cot:
        from cot_buck_spice import FRA_KEYS, normalize_cot_settings
        keys=('enable_delay_ms','soft_start_ms','step_ms','stop_ms','load_after','line_load_enabled','cross_timeout_s',
              'simulation_threads','simulation_timeout_s','comparison_tolerance_pct','include_cap_esl',*FRA_KEYS)
    if parameters.get('parasitic_config'):
        keys=[k for k in keys if k not in ('diode_cj_pf','qr_cds_pf')]
    if not supports_design(parameters):
        messagebox.showinfo('LTspice 闭环','支持固定频率反激、有源钳位正激与准谐振反激的 SSR 闭环。',parent=parent);return
    if container is None:
        window=tk.Toplevel(parent);window.title('通用电源控制器配置与仿真对比')
        window.geometry(f'{min(1580,parent.winfo_screenwidth()-60)}x{min(920,parent.winfo_screenheight()-100)}')
        window.transient(parent)
        window.minsize(1000,620)
    else:
        window=ttk.Frame(container)
        window.pack(fill='both',expand=True)
    owner=window.winfo_toplevel()
    window.columnconfigure(0,weight=1);window.rowconfigure(3,weight=1)
    ui_font=tkfont.nametofont('TkDefaultFont',root=window)
    family=ui_font.cget('family')
    ui_size=abs(int(ui_font.cget('size')))
    compact_size=max(12,min(16,ui_size))
    compact_font=(family,-compact_size)
    field_font=(family,-max(12,min(18,ui_size)))
    section_font=(family,-compact_size,'bold')
    ttk.Style(window).configure('Controller.TButton',font=compact_font,padding=(9,5))
    heading=(f"Buck COT · {int(parameters.get('buck_phases',1))} 相同步交错" if cot else
             profile(parameters)['name'] if noniso else '准谐振反激 · L6565 逻辑参考 / ZCD / CS' if qr else
             '有源钳位正激 · MP6005 / GATE / SYNC / 死区' if forward else '反激控制器 · 频率 / 软启动 / Vcs / 短路逻辑')
    ttk.Label(window,text=heading,font=(family,-max(16,compact_size+2),'bold')).grid(
        row=0,column=0,sticky='w',padx=14,pady=(9,7))
    toolbar=ttk.Frame(window,padding=(14,0));toolbar.grid(row=1,column=0,sticky='ew')
    settings=(normalize_cot_settings(parameters.get('spice_config'),parameters.get('f_sw',100e3))
              if cot else normalize_settings(parameters.get('spice_config')))
    variables={};groups={};traces=[];choice_labels={}
    from spice_planning import recommend_settings,execution_plan,plan_text
    planbar=ttk.Frame(window,padding=(14,6));planbar.grid(row=2,column=0,sticky='ew')
    actions=ttk.Frame(planbar);actions.pack(fill='x')
    plan_label=ttk.Label(planbar,wraplength=1400,justify='left',font=compact_font);plan_label.pack(fill='x',pady=(6,0))
    plan_job=[None]
    body=ttk.Panedwindow(window,orient='horizontal');body.grid(row=3,column=0,sticky='nsew',padx=14,pady=8)
    left=ttk.Frame(body,width=400);left.columnconfigure(0,weight=1);left.rowconfigure(1,weight=1)
    section_title=ttk.Label(left,font=section_font)
    section_title.grid(row=0,column=0,sticky='ew',padx=8,pady=(2,7))
    ttk.Style(window).configure('Controller.TNotebook.Tab',font=compact_font,padding=(4,5))
    notebook=ttk.Notebook(left,style='Controller.TNotebook');notebook.grid(row=1,column=0,sticky='nsew')
    body.add(left,weight=0)
    from spice_logic_ui import ControllerLogicPanel
    logic=ControllerLogicPanel(body,values=lambda:{k:v.get() for k,v in variables.items()},
                               design=parameters,available_keys=keys)
    body.add(logic,weight=1)

    manual_split=False
    def use_manual_split(event):
        nonlocal manual_split
        if body.identify(event.x,event.y) not in ('',None):
            manual_split=True

    def fit_split(event):
        if not manual_split and event.width >= 600:
            body.sashpos(0,min(445,max(312,round(event.width*.34))))

    body.bind('<Configure>',fit_split,add='+')
    body.bind('<ButtonPress-1>',use_manual_split,add='+')
    from scrollable_results import ScrollableResults
    def control_group(key):
        return '开关 FRA' if cot and key in FRA_KEYS else setting_group(key)
    compact_tabs={
        '准谐振与 ZCD':'ZCD', '频率与 PWM':'PWM', '软启动逻辑':'软启',
        '短路与过载保护':'保护', '测试与对比报告':'测试', '环路与交叉调整率':'环路',
        '补偿与寄生':'补偿', 'Buck / Boost 原型':'原型', '有源钳位与 SYNC':'SYNC',
        '开关 FRA':'FRA',
    }
    group_by_page={}
    for group in dict.fromkeys(control_group(k) for k in keys):
        page=ttk.Frame(notebook);notebook.add(page,text=compact_tabs.get(group,group))
        scroll=ScrollableResults(page);scroll.pack(fill='both',expand=True)
        scroll.content.columnconfigure(2,weight=1)
        labels=[];editors=[]
        def size_labels(event, labels=labels, editors=editors):
            if not editors:
                return
            space=event.width-max(widget.winfo_reqwidth() for widget in editors)-30
            for label in labels:
                label.configure(wraplength=max(70,min(232,space)))
        scroll.canvas.bind('<Configure>',size_labels,add='+')
        group_by_page[str(page)]=group
        groups[group]=[scroll.content,0,page,labels,editors]
    for key in keys:
        _,lo,hi,label,unit=SETTINGS[key]
        group=control_group(key)
        form,index,_,form_labels,form_editors=groups[group];groups[group][1]+=1
        row,col=index,0
        label_widget=ttk.Label(form,text=label+(' / '+unit if unit else ''),wraplength=175,
                               justify='left',font=field_font)
        label_widget.grid(row=row,column=col,sticky='w',padx=(8,10),pady=7)
        form_labels.append(label_widget)
        variable=tk.StringVar(value=f'{settings[key]:g}');variables[key]=variable
        if key in CHOICES:
            labels=_choice_labels(key)
            choice_labels[key]=labels
            variable.set(labels[int(settings[key])])
            widget=ttk.Combobox(form,textvariable=variable,values=list(labels.values()),state='readonly',
                                width=17,font=field_font)
        else:widget=ttk.Entry(form,textvariable=variable,width=11,font=field_font)
        widget.grid(row=row,column=col+1,sticky='w',padx=(0,8),pady=7)
        form_editors.append(widget)
        widget.bind('<FocusIn>',lambda _e,k=key:logic.select(k),add='+')
        traces.append((variable,variable.trace_add('write',lambda *_:settings_changed())))
    def remove_traces(event):
        if event.widget is window:
            if plan_job[0] is not None:
                try:window.after_cancel(plan_job[0])
                except tk.TclError:pass
            for variable,trace in traces:
                try:variable.trace_remove('write',trace)
                except tk.TclError:pass
            traces.clear()
    window.bind('<Destroy>',remove_traces,add='+')
    def show_group(_event=None):
        group=group_by_page.get(notebook.select())
        if group is not None:
            section_title.configure(text=group)
            logic.select(next(k for k in keys if control_group(k)==group))
    notebook.bind('<<NotebookTabChanged>>',show_group,add='+')
    if initial_tab in groups:notebook.select(groups[initial_tab][2])
    def read():
        trial=dict(settings,**{k:float(v.get().split(' ·')[0]) for k,v in variables.items()})
        if cot:trial.update(cross_enabled=0.,short_test=0.)
        return normalize_settings(trial)
    def refresh_plan():
        plan_job[0]=None
        try:
            chosen=read()
            if cot:
                from spice_boundary import load_definition
                step=load_definition(parameters,chosen)
                plan_label.configure(text=f"{int(parameters.get('buck_phases',1))} 相，满载从零启动。独立双向阶跃 "
                    f"{step['low_fraction']:.0%} ↔ {step['high_fraction']:.0%}，仿真至 {step['stop_s']*1000:g} ms。"+
                    (f"每个输入端点另运行 {chosen['fra_start_hz']:g}–{chosen['fra_stop_hz']:g} Hz 开关 FRA 和半幅复核。"
                     "上限受单相实际开关频率限制。" if chosen['fra_enabled'] else "未选择开关 FRA。")+
                    ('另做一次线载联合长时试验，输入每档 500 ms。' if chosen['line_load_enabled'] else ''))
            else:
                plan_label.configure(text=plan_text(execution_plan(parameters,chosen)))
        except (ValueError,tk.TclError) as exc:plan_label.configure(text='任务计划：'+str(exc))
    def settings_changed():
        logic.refresh()
        if plan_job[0] is not None:window.after_cancel(plan_job[0])
        plan_job[0]=window.after(180,refresh_plan)
    def put(value):
        for key,number in value.items():
            if key in variables:variables[key].set(choice_labels[key][int(number)] if key in choice_labels else f'{number:g}')
    def choose_plan(scope):
        try:
            put(recommend_settings(parameters,read(),scope))
            status.set('已设置任务范围与观察时间，点击“运行并导出对比报告”。未改变控制器、器件、开关步长或 FRA 分辨率；时序建议仍需实际稳态检查。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查仿真设置',str(exc),parent=window)
    ttk.Label(actions,text='仿真任务',font=section_font).pack(side='left',padx=(0,12))
    if cot:
        def select_cot_fra(enabled):
            put({'fra_enabled': enabled,'line_load_enabled':0})
            if enabled:
                notebook.select(groups['开关 FRA'][2])
        ttk.Button(actions,text='快速瞬态',command=lambda:select_cot_fra(0),style='Controller.TButton').pack(side='left',padx=(0,8))
        ttk.Button(actions,text='加做开关 FRA',command=lambda:select_cot_fra(1),style='Controller.TButton').pack(side='left',padx=(0,8))
        ttk.Button(actions,text='完整对比',command=lambda:put({'fra_enabled':1,'line_load_enabled':1}),style='Controller.TButton').pack(side='left',padx=(0,8))
    else:
        ttk.Button(actions,text='快速预检（推荐）',command=lambda:choose_plan('quick'),style='Controller.TButton').pack(side='left',padx=(0,8))
        ttk.Button(actions,text='完整对比',command=lambda:choose_plan('full'),style='Controller.TButton').pack(side='left',padx=(0,8))
        ttk.Button(actions,text='仅建议观察时间',command=lambda:choose_plan(None),style='Controller.TButton').pack(side='left')
    window.bind('<Configure>',lambda e:plan_label.configure(wraplength=max(480,e.width-42))
                if e.widget is window else None,add='+')
    refresh_plan()
    def apply_only():
        try:
            apply_settings(read())
            status.set('已应用本次仿真设置。' if cot else '参数已应用；更换原型后请重新检查环路整定。仅导出工程不运行仿真；对比报告会运行 LTspice。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查控制器参数',str(exc),parent=window)
    def fill_reference():
        try:
            chosen=read()
            if noniso:
                number=int(chosen['niso_profile']) or profile(parameters)['id']
                put(reference_settings(number,chosen))
            elif qr:
                put(l6565_preset())
            elif forward:
                put(acf_preset())
            else:
                put(mp6005_preset())
            status.set('已填入控制器参考值；保留 DCR、软启动、补偿与测试设置。请应用到计算器。' if noniso else '已填入参考值，请应用到计算器。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查控制器参数',str(exc),parent=window)
    ttk.Button(toolbar,text='应用到计算器',command=apply_only,style='Controller.TButton').pack(side='right')
    if not cot:
        ttk.Button(toolbar,text='填入控制器参考值' if noniso else '填入 L6565 QR 参考配置' if qr else '填入 MP6005 正激参考配置' if forward else '填入 MP6005 SSR 参考配置',command=fill_reference,style='Controller.TButton').pack(side='left')
        ttk.Button(toolbar,text='恢复全部默认' if noniso else '恢复 QR 参考默认' if qr else '恢复通用默认',command=lambda:put(preset(profile(parameters)['id']) if noniso else l6565_preset() if qr else normalize_settings()),style='Controller.TButton').pack(side='left',padx=8)
    ttk.Label(toolbar,text=('导通时间、标称单相频率和相数取自设计参数' if cot else
        '原创可配置模型，不含独立原厂模型验证' if noniso else 'L6565 参考 · ZCD 事件驱动行为模型' if qr else 'MP6005 参考 · 可配置行为模型'),style='Muted.TLabel',font=compact_font).pack(side='left',padx=10)
    if parameters.get('parasitic_config'):
        ttk.Label(toolbar,text='Coss / Cj 在主界面「寄生参数与吸收」设置',style='Muted.TLabel',font=compact_font).pack(side='left')
    from spice_runtime import find_ltspice,set_ltspice
    runtime=ttk.Frame(window,padding=(14,0));runtime.grid(row=4,column=0,sticky='ew')
    if settings_context is None:
        executable=tk.StringVar(window,find_ltspice() or '尚未检测到 LTspice')
        def choose():
            filename=filedialog.askopenfilename(parent=owner,title='选择 LTspice.exe',filetypes=[('LTspice 程序','*.exe')])
            if not filename:return
            try:set_ltspice(filename);executable.set(filename)
            except ValueError as exc:messagebox.showerror('LTspice 路径',str(exc),parent=owner)
        ttk.Button(runtime,text='选择 LTspice.exe…',command=choose,style='Controller.TButton').pack(side='right')
    else:
        executable=settings_context.executable
        ttk.Button(runtime,text='设备与模型…',command=lambda:navigate('tools'),style='Controller.TButton').pack(side='right')
    ttk.Label(runtime,textvariable=executable,wraplength=830,font=compact_font).pack(side='left',fill='x',expand=True)
    ttk.Label(window,text=('对比报告包含各相瞬态波形。启用 FRA 后在电容反馈端注入，按半幅复核计算环路裕度。' if cot else
        '单路无交叉调整率。默认快速闭环不验证结电容尖峰；LM5022 限流包含斜坡。Boost 关闭 MOS 不会切断输入至输出的短路通路。' if noniso else 'QR：f_sw 为设计频率上限；ZCD 决定实际周期。异常 CS 锁存至 VCC 欠压；理想供电不模拟自动打嗝。' if qr else 'Vcs 为原始采样端阈值，实际峰值含消隐与延时超调。保护后重启会复位软启动；340 ms 打嗝若超过观察时间，不宣称已观察到重启。'),wraplength=970,font=compact_font).grid(row=5,column=0,sticky='w',padx=14,pady=5)
    status=tk.StringVar(value='仅导出 ASC 工程不运行仿真。对比报告会运行各输入端点，可取消。' if cot else
        '已加载示例时可直接导出。仅导出 ASC 工程不运行仿真；运行对比报告会依次仿真输入端点及 FRA，可取消。')
    bar=ttk.Frame(window,padding=(14,8));bar.grid(row=6,column=0,sticky='ew')
    ttk.Label(bar,textvariable=status,wraplength=460,font=compact_font).pack(side='left',fill='x',expand=True)
    cancellation=threading.Event()
    panel_job=[None]

    def circuit_identity(p):
        return p.get('topology'),p.get('feedback_mode','SSR'),p.get('control_mode'),cot_active(p)

    def start(compare=False):
        try:chosen=read();p=copy.deepcopy(get_parameters() if get_parameters else parameters)
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查设置',str(exc),parent=window);return
        if circuit_identity(p)!=circuit_identity(parameters):
            messagebox.showerror('控制模式已变更','请从当前设计重新打开电路仿真设置。',parent=owner);return
        path_to_spice=None
        if compare:
            try:
                path_to_spice=settings_context.spice_path() if settings_context else find_ltspice()
                if not path_to_spice:
                    raise ValueError('请先选择 LTspice.exe。')
            except ValueError as exc:
                if navigate:
                    navigate('tools')
                messagebox.showerror('尚未检测到 LTspice',str(exc),parent=owner)
                return
        path=filedialog.asksaveasfilename(parent=window,title='仿真与设计计算对比报告' if compare else '导出 LTspice 工程',
            defaultextension='.docx' if compare else '.zip',filetypes=[('Word 对比报告','*.docx')] if compare else [('LTspice 工程','*.zip')],
            initialfile='仿真与设计计算对比报告.docx' if compare else 'Buck_COT_LTspice.zip' if cot else parameters['topology']+'_LTspice.zip' if noniso else '有源钳位正激_LTspice.zip' if forward else '反激闭环_LTspice.zip')
        if not path:return
        apply_settings(chosen);p['spice_config']=chosen;cancellation.clear()
        for button in (export_button,compare_button):button.configure(state='disabled')
        cancel_button.configure(state='normal');latest=['正在后台准备…'];status.set(latest[0])
        started=time.monotonic()
        executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='spice-operation')
        def operation():
            if not compare:return export_project(path,p)
            from design_engine.service import calculate_parameters
            from spice_runtime import compare_design
            run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False,cancelled=cancellation.is_set)
            options=dict(cancelled=cancellation.is_set,progress=lambda d,t,label:latest.__setitem__(0,f'{d}/{t} '+label))
            if settings_context is not None:
                options['executable']=path_to_spice
            return compare_design(run,path,**options)
        future=executor.submit(operation)
        panel_job[0]=future
        executor.shutdown(wait=False)
        def poll():
            if not future.done():
                if window.winfo_exists():status.set(latest[0]+f' · 已用时 {int(time.monotonic()-started)} s')
                if parent.winfo_exists():parent.after(150,poll)
                return
            panel_job[0]=None
            if not window.winfo_exists():return
            for button in (export_button,compare_button):button.configure(state='normal')
            cancel_button.configure(state='disabled')
            try:
                result=future.result()
                if compare:
                    level,title,message=comparison_feedback(result)
                    status.set(title+'：'+str(path))
                    (messagebox.showwarning if level=='warning' else messagebox.showinfo)(title,message+str(path),parent=window)
                else:
                    status.set('工程已导出：'+str(path))
                    description=('使用 LTspice 打开 Flyback.asc 查看相位结构。功率级和控制电路可在对应 INCLUDE 文件中编辑。'
                                 if cot else '使用 LTspice 打开 Flyback.asc，可看到功率级与控制器连接。')
                    messagebox.showinfo('工程已导出',description+'\n'+str(path),parent=window)
            except Exception as exc:status.set('操作未完成');messagebox.showerror('仿真与导出',str(exc) or '已取消',parent=window)
        parent.after(150,poll)
    export_button=ttk.Button(bar,text='导出 ASC 工程…',command=lambda:start(False),style='Controller.TButton');export_button.pack(side='left',padx=4)
    compare_button=ttk.Button(bar,text='运行并导出对比报告…',command=lambda:start(True),style='Controller.TButton');compare_button.pack(side='left',padx=4)
    cancel_button=ttk.Button(bar,text='取消',command=cancellation.set,state='disabled',style='Controller.TButton');cancel_button.pack(side='left',padx=4)
    def close():cancellation.set();window.destroy()
    window.bind('<Destroy>',lambda event:cancellation.set() if event.widget is window else None,add='+')
    if container is None:
        window.protocol('WM_DELETE_WINDOW',close)
    from types import SimpleNamespace
    return SimpleNamespace(frame=window,cancel=cancellation.set,busy=lambda:panel_job[0] is not None,
                           edit_group=lambda group:notebook.select(groups[group][2]) if group in groups else None)
