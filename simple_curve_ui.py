"""One small scale-selection dialog, no physical-unit fields in the curve file."""
import tkinter as tk
from tkinter import ttk,messagebox
from simple_curves import to_transfer,to_charge

SCALES={'1（原数值）':1.,'10^-3（m）':1e-3,'10^-6（u）':1e-6,'10^-9（n）':1e-9,'10^-12（p）':1e-12,'10^3（k）':1e3,'10^6（M）':1e6}


def _place_dialog(dialog,owner):
    """Center on the actual application window, not Windows' last dialog origin."""
    dialog.update_idletasks()
    width=max(620,dialog.winfo_reqwidth())
    height=max(470,dialog.winfo_reqheight())
    screen_w,screen_h=dialog.winfo_screenwidth(),dialog.winfo_screenheight()
    width=min(width,max(1,screen_w-32));height=min(height,max(1,screen_h-96))
    x=owner.winfo_rootx()+(owner.winfo_width()-width)//2
    y=owner.winfo_rooty()+(owner.winfo_height()-height)//2
    x=max(16,min(x,screen_w-width-16))
    y=max(32,min(y,screen_h-height-64))
    dialog.geometry(f'{width}x{height}+{x}+{y}')


def import_simple(parent,data,kind,target=''):
    owner=parent.winfo_toplevel()
    dialog=tk.Toplevel(owner);dialog.title('导入曲线与数量级');dialog.transient(owner)
    dialog.geometry('620x470');dialog.minsize(560,440)
    body=ttk.Frame(dialog,padding=14);body.pack(fill='both',expand=True)
    gate=kind=='gate_charge'
    diode=kind=='diode'
    guide = ('横轴为正向压降 Vf / V，纵轴为正向电流 If / A。用于计算导通损耗。' if diode else
             '横轴为栅电荷 Qg / C，纵轴为栅源电压 Vgs / V。' if gate else
             '横轴为栅源电压 Vgs / V，纵轴为漏极电流 Id / A。')
    intro = f'绑定目标 · {target}' if target else '选择曲线并核对坐标单位'
    ttk.Label(body, text=intro, style='ResultConclusion.TLabel', wraplength=540,
              justify='left').pack(fill='x', pady=(0, 4))
    ttk.Label(body, text=guide + '\n已换算至基本单位的数据，倍率选 1。沿用原图单位的数据，按横纵轴选择 m、µ、n 等倍率。'
              '\nCSV 用 x,y 两列，JSON 用点数组。超出数据范围时显示外推提示。',
              wraplength=530, justify='left').pack(fill='x')
    if diode:
        ttk.Label(body, text='描点回退不超过 Vf 跨度的 3% 时自动整理，并记录修正量。回退更大时需要校核。',
                  wraplength=530, justify='left').pack(fill='x', pady=(4, 0))
    box=tk.Listbox(body,height=min(5,len(data['curves'])),exportselection=False)
    for c in data['curves']:box.insert('end',c['name']+f"  {len(c['points'])} 点")
    box.pack(fill='x',pady=10);box.selection_set(0)
    limits=tk.StringVar()
    ttk.Label(body,textvariable=limits,wraplength=580).pack(fill='x',pady=(0,5))
    def show_limits(*_):
        selected=box.curselection()
        if not selected:return
        points=data['curves'][selected[0]]['points']
        limits.set(f"文件数值 · X {min(p[0] for p in points):.5g} 至 {max(p[0] for p in points):.5g} · "
                   f"Y {min(p[1] for p in points):.5g} 至 {max(p[1] for p in points):.5g}")
    box.bind('<<ListboxSelect>>',show_limits);show_limits()
    form=ttk.Frame(body);form.pack(fill='x')
    x=tk.StringVar(value='1（原数值）');y=tk.StringVar(value='1（原数值）')
    for r,(text,var) in enumerate((('X 数量级',x),('Y 数量级',y))):
        ttk.Label(form,text=text).grid(row=r,column=0,sticky='w',pady=5)
        ttk.Combobox(form,textvariable=var,values=list(SCALES),state='readonly',width=20).grid(row=r,column=1,sticky='w',padx=10)
    start=tk.StringVar();end=tk.StringVar()
    if gate:
        for r,(text,var) in enumerate((('平台起点 X（原数值）',start),('平台终点 X（原数值）',end)),2):
            ttk.Label(form,text=text).grid(row=r,column=0,sticky='w',pady=4)
            ttk.Entry(form,textvariable=var,width=22).grid(row=r,column=1,sticky='w',padx=10)
        def suggest(*_):
            show_limits()
            try:
                from simple_curves import cleaned_points
                from mos_gate_charge import suggest_plateau
                c=data['curves'][box.curselection()[0]]
                a,b=suggest_plateau(cleaned_points(c['points'])[0]);start.set(f'{a:.9g}');end.set(f'{b:.9g}')
            except (ValueError,IndexError):start.set('');end.set('')
        box.bind('<<ListboxSelect>>',suggest);suggest()
        ttk.Label(body, text='平台位置可直接修改。填写原图横轴上的数值。',
                  wraplength=530, justify='left').pack(fill='x', pady=8)
    result=[]
    def accept():
        try:
            selected=box.curselection()
            if not selected:raise ValueError('请选择一条曲线')
            curve=data['curves'][selected[0]];args=dict(x_multiplier=SCALES[x.get()],y_multiplier=SCALES[y.get()],source=data['source'])
            if gate:
                args.update(start=float(start.get()) if start.get().strip() else None,end=float(end.get()) if end.get().strip() else None)
                value=to_charge(curve,**args)
            elif diode:
                from diode_curves import from_xy
                value=from_xy(curve,**args)
            else:value=to_transfer(curve,**args)
            result.append(value);dialog.destroy()
        except (ValueError,OverflowError) as exc:messagebox.showerror('请核对导入设置',str(exc),parent=dialog)
    buttons=ttk.Frame(body);buttons.pack(side='bottom',fill='x',pady=8)
    ttk.Button(buttons,text='确认数量级并导入',command=accept).pack(side='right')
    ttk.Button(buttons,text='取消',command=dialog.destroy).pack(side='right',padx=8)
    _place_dialog(dialog,owner)
    dialog.grab_set();owner.wait_window(dialog)
    return result[0] if result else None
