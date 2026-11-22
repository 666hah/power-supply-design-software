"""Grouped controller settings and owned simulation/comparison operations."""
import copy
from concurrent.futures import ThreadPoolExecutor
from tkinter import font as tkfont
import threading
import time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from spice_export import SETTINGS,CHOICES,setting_group,ordered_setting_keys,normalize_settings,mp6005_preset,export_project


_FORM_LABELS = {
    'load_after': 'ASC 阶跃后负载比例',
    'simulation_reuse': '标称结果复用方式',
    'line_load_enabled': '输入与负载联合跳变',
    'qr_cds_pf': '漏极等效谐振电容',
    'qr_aux_ratio': 'ZCD 辅助绕组匝比',
    'qr_zcd_winding': 'ZCD 取样位置',
    'qr_zcd_c_pf': 'ZCD 等效输入电容',
    'qr_zcd_delay_ns': 'ZCD 附加延时',
    'qr_zcd_arm_v': 'ZCD 上升沿预备阈值',
    'qr_zcd_trigger_v': 'ZCD 下降沿触发阈值',
    'qr_off_light_us': '轻载关断消隐时间',
    'qr_vff_v': '输入电压前馈 VFF',
    'qr_max_on_us': '看门狗最大导通时间',
    'acf_dead_ns': 'GATE／SYNC 死区',
    'niso_profile': '控制器原型',
    'niso_ramp_ratio': '斜坡幅值与输入电压比',
    'niso_ith_gain': 'ITH 至 CS 等效增益',
    'niso_lm_cs_resistor': 'LM5022 CS 滤波电阻',
    'niso_inductor_dcr': '仿真电感 DCR',
    'niso_edge_model': '开关边沿模型',
}


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
    counts=(f"瞬态 {result['successful']}/{result['total']} · "
        f"环路 FRA {result['fra_successful']}/{result['fra_total']} · "
        f"交叉调整率 {result['cross_successful']}/{result['cross_total']}\n")
    if result.get('cached_nominal'):counts+=f"复用 {result['cached_nominal']} 个有效标称工况。\n"
    if not result['successful']:
        return 'warning','仿真未完成','没有有效仿真对比数据。诊断报告与工程 ZIP 已保存。\n'+counts+'请查看各工况的日志与失败原因。\n'
    if result['incomplete']:
        return 'warning','对比部分完成','部分项目待复核。请查看报告中的状态和原因。\n'+counts+'报告与同名工程 ZIP 已保存。\n'
    formats = 'Word、Excel 报告' if result.get('xlsx_path') else 'Word 报告'
    return 'info','对比已完成',formats+'与同名仿真工程 ZIP 已输出。\n'+counts


def supports_design(parameters):
    return (parameters.get('topology') in ('FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST','LLC')
            and parameters.get('feedback_mode','SSR') == 'SSR')


def open_export_dialog(parent,parameters,apply_settings,*,get_parameters=None,initial_tab=None,
                       container=None,settings_context=None,navigate=None):
    qr=parameters.get('topology')=='QR-FLYBACK'
    llc=parameters.get('topology')=='LLC'
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
    if llc:
        keys=('enable_delay_ms','step_ms','stop_ms','simulation_threads','simulation_timeout_s',
              'comparison_tolerance_pct','include_cap_esl','fra_enabled','fra_start_hz',
              'fra_stop_hz','fra_oct','fra_amplitude_pct','fra_timeout_s')
    if cot:
        from cot_buck_spice import FRA_KEYS, normalize_cot_settings
        keys=('enable_delay_ms','soft_start_ms','step_ms','stop_ms','load_after','line_load_enabled','cross_timeout_s',
              'simulation_threads','simulation_timeout_s','comparison_tolerance_pct','include_cap_esl',*FRA_KEYS)
    if parameters.get('parasitic_config'):
        keys=[k for k in keys if k not in ('diode_cj_pf','qr_cds_pf')]
    if not supports_design(parameters):
        messagebox.showinfo('电路仿真','当前拓扑或反馈模式暂未接入 LTspice 闭环对比。',parent=parent);return
    if container is None:
        window=tk.Toplevel(parent);window.title('电路仿真与设计对比')
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
    heading=(f"LLC {'半桥' if parameters['llc_bridge']=='half' else '全桥'} · "
             f"{'混合滞环' if parameters['control_mode']=='Hybrid Hysteretic' else '电压变频'}" if llc else
             f"Buck COT · {int(parameters.get('buck_phases',1))} 相同步交错" if cot else
             profile(parameters)['name'] if noniso else '准谐振反激 · L6565 逻辑参考' if qr else
             '有源钳位正激 · MP6005 逻辑参考' if forward else '反激 · 控制器与测试配置')
    header=ttk.Frame(window);header.grid(row=0,column=0,sticky='ew',padx=14,pady=(8,6))
    ttk.Label(header,text=heading,font=(family,-max(16,compact_size+2),'bold')).pack(anchor='w')
    status=tk.StringVar(value='未运行 · 选择试验范围后，可运行并导出对比报告。')
    status_label=ttk.Label(header,textvariable=status,style='ResultConclusion.TLabel',wraplength=970,justify='left')
    status_label.pack(fill='x',pady=(4,0))
    toolbar=ttk.Frame(window,padding=(14,0));toolbar.grid(row=1,column=0,sticky='ew')
    settings=(normalize_cot_settings(parameters.get('spice_config'),parameters.get('f_sw',100e3))
              if cot else normalize_settings(parameters.get('spice_config')))
    variables={};groups={};traces=[];choice_labels={}
    from spice_planning import recommend_settings,execution_plan,plan_text,resource_text
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
    if llc:
        from llc_ui import SimulationLogicPanel
        logic=SimulationLogicPanel(body,parameters)
    else:
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
        '准谐振与 ZCD':'ZCD', '频率与 PWM':'PWM', '软启动逻辑':'软启动',
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
        label_widget=ttk.Label(form,text=_FORM_LABELS.get(key,label)+(' / '+unit if unit else ''),wraplength=175,
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
                text=(f"{int(parameters.get('buck_phases',1))} 相，满载从零启动。独立双向阶跃 "
                    f"{step['low_fraction']:.0%} ↔ {step['high_fraction']:.0%}，仿真至 {step['stop_s']*1000:g} ms。"+
                    (f"每个输入端点另运行 {chosen['fra_start_hz']:g}–{chosen['fra_stop_hz']:g} Hz 开关 FRA 和半幅复核。"
                     "上限受单相实际开关频率限制。" if chosen['fra_enabled'] else "未选择开关 FRA。")+
                    ('另做一次线载联合长时试验，输入每档 500 ms。' if chosen['line_load_enabled'] else ''))
            else:
                text=plan_text(execution_plan(parameters,chosen)).replace('；',' · ')
            plan_label.configure(text=text+'\n'+resource_text(parameters,chosen))
        except (ValueError,tk.TclError) as exc:plan_label.configure(text='试验范围待确认 · '+str(exc))
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
            status.set('试验范围与观察时间已更新 · 运行后按波形检查稳态。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查仿真设置',str(exc),parent=window)
    ttk.Label(actions,text='试验范围',font=section_font).pack(side='left',padx=(0,12))
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
    refresh_plan()
    def apply_only():
        try:
            apply_settings(read())
            status.set('设置已应用。' if cot else '设置已应用 · 若更换了控制器原型，请复核环路整定。')
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
            status.set('参考值已填入 · 点击「应用到计算器」保存当前设置。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查控制器参数',str(exc),parent=window)
    ttk.Button(toolbar,text='应用到计算器',command=apply_only,style='Controller.TButton').pack(side='right')
    if not cot and not llc:
        ttk.Button(toolbar,text='填入控制器参考值' if noniso else '填入 L6565 QR 参考配置' if qr else '填入 MP6005 正激参考配置' if forward else '填入 MP6005 SSR 参考配置',command=fill_reference,style='Controller.TButton').pack(side='left')
        ttk.Button(toolbar,text='恢复全部默认' if noniso else '恢复 QR 参考默认' if qr else '恢复通用默认',command=lambda:put(preset(profile(parameters)['id']) if noniso else l6565_preset() if qr else normalize_settings()),style='Controller.TButton').pack(side='left',padx=8)
    if not llc:
        ttk.Label(toolbar,text=('相数、频率与导通时间取自设计参数' if cot else '控制器行为模型'),
                  style='Muted.TLabel',font=compact_font).pack(side='left',padx=10)
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
    model_scope=('启用 FRA 后在电容反馈端注入，并以半幅复测核对各相开关模型的环路裕度。' if cot else
                 '电路仿真复用当前桥式结构与控制模式。按选定范围运行瞬态或环路测试。' if llc else
                 '快速闭环省略结电容尖峰。LM5022 限流包含斜坡。Boost 关断 MOS 后仍有输入到输出的短路通路。' if noniso else
                 'ZCD 决定实际周期。f_sw 为设计频率上限。异常 CS 锁存至 VCC 欠压，理想 VCC 模型下无自动打嗝。' if qr else
                 'Vcs 是采样端阈值，峰值还受消隐与延时影响。保护重启会复位软启动，打嗝重启须由观察窗口覆盖。')
    if parameters.get('parasitic_config'):
        model_scope += ' Coss、Cj 在「寄生参数与吸收」设置。'
    scope_label=ttk.Label(window,text=model_scope,wraplength=970,font=compact_font,style='Muted.TLabel',justify='left')
    scope_label.grid(row=5,column=0,sticky='ew',padx=14,pady=(4,2))

    def wrap_notes(event):
        if event.widget is window:
            for label in (status_label,plan_label,scope_label):
                label.configure(wraplength=max(400,event.width-42))
    window.bind('<Configure>',wrap_notes,add='+')
    bar=ttk.Frame(window,padding=(14,8));bar.grid(row=6,column=0,sticky='ew')
    ttk.Label(bar,text='导出 ASC 可单独查看或运行工程。',font=compact_font,style='Muted.TLabel').pack(side='right')
    cancellation=threading.Event()
    panel_job=[None]

    def circuit_identity(p):
        return (p.get('topology'),p.get('feedback_mode','SSR'),p.get('control_mode'),
                cot_active(p),p.get('llc_bridge') if llc else None)

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
        path=filedialog.asksaveasfilename(parent=window,title='保存仿真对比报告 · Word 与 Excel' if compare else '导出 LTspice 工程',
            defaultextension='.docx' if compare else '.zip',filetypes=[('Word 对比报告','*.docx'),('Excel 对比报告','*.xlsx')] if compare else [('LTspice 工程','*.zip')],
            initialfile='仿真与设计计算对比报告.docx' if compare else 'Buck_COT_LTspice.zip' if cot else parameters['topology']+'_LTspice.zip' if noniso or llc else '有源钳位正激_LTspice.zip' if forward else '反激闭环_LTspice.zip')
        if not path:return
        apply_settings(chosen);p['spice_config']=chosen;cancellation.clear()
        for button in (export_button,compare_button):button.configure(state='disabled')
        cancel_button.configure(state='normal');latest=['准备输入'];status.set('运行中 · '+latest[0])
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
                if window.winfo_exists():
                    state='正在取消' if cancellation.is_set() else '运行中'
                    status.set(f'{state} · {latest[0]} · {int(time.monotonic()-started)} s')
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
                    status.set(title+' · '+str(path))
                    from pathlib import Path
                    names = [result[k] for k in ('report_path','xlsx_path') if result.get(k)]
                    saved = ('\n'.join(Path(name).name for name in names)+'\n'+str(Path(path).parent)) if names else str(path)
                    (messagebox.showwarning if level=='warning' else messagebox.showinfo)(title,message+saved,parent=window)
                else:
                    status.set('工程已导出 · '+str(path))
                    description=('在 Vinmin / Vinmax 子文件夹中运行 LLC.asc。' if llc else
                                 '使用 LTspice 打开 Flyback.asc 查看相位结构。功率级和控制电路可在对应 INCLUDE 文件中编辑。'
                                 if cot else '使用 LTspice 打开 Flyback.asc，可看到功率级与控制器连接。')
                    messagebox.showinfo('工程已导出',description+'\n'+str(path),parent=window)
            except Exception as exc:
                if cancellation.is_set():
                    status.set('已取消 · '+(str(exc) or '请查看运行记录。'))
                    messagebox.showinfo('已取消',str(exc) or '本次操作已取消。',parent=window)
                else:
                    status.set('失败 · '+(str(exc) or type(exc).__name__))
                    messagebox.showerror('仿真与导出',str(exc) or type(exc).__name__,parent=window)
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
