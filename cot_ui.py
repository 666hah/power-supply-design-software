"""Non-modal editor for one shared COT engineering configuration."""
import copy
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from cot_settings import configuration
from cot_ui_schema import schema, get_value, set_value


class CotEditor:
    def __init__(self, parent, parameters, apply):
        self.parameters, self.apply_callback = copy.deepcopy(parameters), apply
        self.data = copy.deepcopy(parameters.get('cot_config') or {})
        self.meta = schema()
        self.window = tk.Toplevel(parent)
        self.window.title('COT 多相 Buck · 控制、均流、保护与验收')
        width=min(1480,max(840,parent.winfo_screenwidth()-100))
        height=min(900,max(560,parent.winfo_screenheight()-140))
        self.window.geometry(f'{width}x{height}')
        self.window.minsize(840,560)
        self.window.columnconfigure(0,weight=1)
        self.window.rowconfigure(1,weight=1)
        ttk.Label(self.window,text='COT 工程配置',font=('',16,'bold'),padding=(16,12)).grid(sticky='w')
        self.tabs=ttk.Notebook(self.window)
        self.tabs.grid(row=1,column=0,sticky='nsew',padx=12)
        self.variables={}
        self.scroll_canvases=[]
        for group in self.meta['groups']:
            frame=self._page(group['name'])
            frame.columnconfigure(2,weight=1)
            for row,field in enumerate(group['fields']):
                label=field['label']+(' / '+field['unit'] if field['unit'] else '')
                ttk.Label(frame,text=label,wraplength=310).grid(row=row,column=0,sticky='w',padx=8,pady=8)
                var=tk.StringVar()
                self.variables[field['key']]=(var,field)
                if field['choices']:
                    widget=ttk.Combobox(frame,textvariable=var,values=list(field['choices'].values()),state='readonly',width=26)
                else:
                    widget=ttk.Entry(frame,textvariable=var,width=23)
                widget.grid(row=row,column=1,sticky='ew',padx=8,pady=8)
                ttk.Label(frame,text=field['note'],wraplength=440,foreground='#526579').grid(row=row,column=2,sticky='w',padx=8,pady=8)
        self._phase_page()
        self.status=tk.StringVar(value='修改后点击“应用到当前设计”；保存工程时会一起保存。')
        bar=ttk.Frame(self.window,padding=12)
        bar.grid(row=2,column=0,sticky='ew')
        bar.columnconfigure(0,weight=1)
        ttk.Label(bar,textvariable=self.status,wraplength=550).grid(row=0,column=0,sticky='w')
        ttk.Button(bar,text='导入配置…',command=self.import_config).grid(row=0,column=1,padx=4)
        ttk.Button(bar,text='导出配置…',command=self.export_config).grid(row=0,column=2,padx=4)
        ttk.Button(bar,text='应用到当前设计',command=self.apply).grid(row=0,column=3,padx=4)
        ttk.Button(bar,text='关闭',command=self.window.destroy).grid(row=0,column=4,padx=4)
        self.reload()

    def _page(self,title):
        page=ttk.Frame(self.tabs)
        self.tabs.add(page,text=title)
        page.columnconfigure(0,weight=1);page.rowconfigure(0,weight=1)
        canvas=tk.Canvas(page,highlightthickness=0)
        self.scroll_canvases.append(canvas)
        bar=ttk.Scrollbar(page,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=0,column=0,sticky='nsew');bar.grid(row=0,column=1,sticky='ns')
        inner=ttk.Frame(canvas,padding=8)
        item=canvas.create_window((0,0),window=inner,anchor='nw')
        inner.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=max(e.width,760)))
        def wheel(e):
            canvas.yview_scroll(int(-e.delta/120),'units')
        page.bind('<MouseWheel>',wheel)
        canvas.bind('<MouseWheel>',wheel)
        return inner

    def _phase_page(self):
        frame=self._page('逐相器件与采样')
        frame.columnconfigure(0,weight=1)
        self.phase_note=tk.StringVar()
        ttk.Label(frame,textvariable=self.phase_note,wraplength=1000).grid(sticky='w',pady=8)
        fields=self.meta['phase_fields']
        self.phase_table=ttk.Treeview(frame,columns=[x['key'] for x in fields],show='tree headings',height=16,selectmode='browse')
        self.phase_table.heading('#0',text='相');self.phase_table.column('#0',width=50,stretch=False)
        for field in fields:
            self.phase_table.heading(field['key'],text=field['label'])
            self.phase_table.column(field['key'],width=125,minwidth=95)
        self.phase_table.grid(row=1,column=0,sticky='ew')
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=self.phase_table.xview)
        horizontal.grid(row=2,column=0,sticky='ew')
        self.phase_table.configure(xscrollcommand=horizontal.set)
        self.phase_table.bind('<<TreeviewSelect>>',self.select_phase)
        edit=ttk.Frame(frame);edit.grid(row=3,column=0,sticky='ew',pady=10)
        self.phase_variables={}
        for i,field in enumerate(fields):
            ttk.Label(edit,text=field['label']).grid(row=(i//4)*2,column=i%4,sticky='w',padx=6)
            var=tk.StringVar(value=str(self.meta['phase_defaults'][field['key']]))
            self.phase_variables[field['key']]=var
            ttk.Entry(edit,textvariable=var,width=20).grid(row=(i//4)*2+1,column=i%4,sticky='ew',padx=6,pady=5)
        buttons=ttk.Frame(frame);buttons.grid(row=4,column=0,sticky='w',pady=8)
        ttk.Button(buttons,text='更新选中相',command=self.update_phase).pack(side='left',padx=5)
        ttk.Button(buttons,text='增加一相参数',command=self.add_phase).pack(side='left',padx=5)
        ttk.Button(buttons,text='删除选中相参数',command=self.delete_phase).pack(side='left',padx=5)
        ttk.Label(frame,text='倍率作用于主界面的单相标称参数；偏置单位为 A。相数改变后需明确增加或删除参数行。',wraplength=1000).grid(row=5,column=0,sticky='w',pady=8)

    def reload(self):
        for key,(var,field) in self.variables.items():
            value=get_value(self.data,key,field['default'])
            var.set(field['choices'].get(value,str(value)) if field['choices'] else f"{value*field['factor']:.10g}")
        rows=self.data.get('phase_parameters')
        self.rows=copy.deepcopy(rows if rows is not None else [dict(self.meta['phase_defaults']) for _ in range(int(self.parameters['buck_phases']))])
        self.selected=None
        self.refresh_phases()

    def refresh_phases(self):
        self.phase_table.delete(*self.phase_table.get_children())
        for i,row in enumerate(self.rows):
            values=[f"{row.get(x['key'],self.meta['phase_defaults'][x['key']]):.8g}" for x in self.meta['phase_fields']]
            self.phase_table.insert('', 'end',iid=str(i),text=f'PH{i+1}',values=values)
        self.phase_note.set(f"当前 Buck 为 {int(self.parameters['buck_phases'])} 相，已配置 {len(self.rows)} 行。各相可以独立修改。")

    def select_phase(self,_event=None):
        selection=self.phase_table.selection()
        if not selection:return
        self.selected=int(selection[0])
        for key,var in self.phase_variables.items():
            var.set(str(self.rows[self.selected].get(key,self.meta['phase_defaults'][key])))

    def update_phase(self):
        if self.selected is None:return
        try:
            index=self.selected
            self.rows[index]={key:float(var.get()) for key,var in self.phase_variables.items()}
            self.refresh_phases();self.phase_table.selection_set(str(index))
        except ValueError:
            messagebox.showerror('逐相参数','请填写有效数字。',parent=self.window)

    def add_phase(self):
        if len(self.rows)>=16:return
        self.rows.append(dict(self.meta['phase_defaults']));self.selected=None;self.refresh_phases()

    def delete_phase(self):
        if self.selected is None:return
        self.rows.pop(self.selected);self.selected=None;self.refresh_phases()

    def collect(self):
        data=copy.deepcopy(self.data)
        for key,(var,field) in self.variables.items():
            if field['choices']:
                value=next(k for k,v in field['choices'].items() if v==var.get())
            else:value=float(var.get())/field['factor']
            set_value(data,key,value)
        if self.selected is not None:
            self.rows[self.selected]={key:float(var.get()) for key,var in self.phase_variables.items()}
        data['phase_parameters']=copy.deepcopy(self.rows)
        result=configuration(dict(self.parameters,cot_config=data))
        from cot_acceptance import limits
        limits(dict(self.parameters,cot_config=result))
        return result

    def apply(self):
        try:
            data=self.collect()
            self.apply_callback(data)
            self.data=data
            self.status.set('已应用到当前设计。点击主界面“保存工程”可永久保存。')
        except Exception as exc:
            messagebox.showerror('请检查 COT 配置',str(exc),parent=self.window)

    def export_config(self):
        try:
            data=self.collect()
            path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',initialfile='COT工程配置.json',filetypes=[('JSON','*.json')])
            if path:
                with open(path,'w',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
        except Exception as exc:messagebox.showerror('导出配置',str(exc),parent=self.window)

    def import_config(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('JSON','*.json')])
        if not path:return
        try:
            with open(path,encoding='utf-8') as stream:data=json.load(stream)
            self.data=configuration(dict(self.parameters,cot_config=data))
            self.reload();self.status.set('已载入，点击“应用到当前设计”后生效。')
        except Exception as exc:messagebox.showerror('导入配置',str(exc),parent=self.window)


def show(parent,parameters,apply):
    return CotEditor(parent,parameters,apply)
