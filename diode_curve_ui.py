"""Import saved curve data for a diode in the corresponding device group."""
import json
from tkinter import filedialog,messagebox

from diode_curves import active_diodes,validate_curve


class DiodeCurveUI:
    def _diode_context(self):
        p=dict(topology=self._topo_key(),feedback_mode=self._effective_feedback_mode(),
               control_mode=self._ctrl_key(),
               d_in_enable=self.params['d_in_enable'].get(),d_out_enable=self.params['d_out_enable'].get(),outputs=[])
        if self._multiple_active():
            try:count=self._read_output_count()
            except ValueError:count=max(1,len(self.output_config))
            for i in range(count):
                variables=self._inline_output_vars[i]
                p['outputs'].append(dict(name=variables['name'].get(),d_out_enable=variables['d_out_enable'].get()))
        return p

    def _update_diode_result_readout(self,res):
        self._diode_result_models={m['ref']:m for m in res.get('diode_models',[])}
        self._sync_device_curve_controls()

    def _import_diode_curve(self, reference):
        target=next((row for row in active_diodes(self._diode_context()) if row['ref']==reference),None)
        if not target:
            return
        caption=target['ref']+' · '+target['role']
        path=filedialog.askopenfilename(parent=self.root,title=caption+'：导入 X=Vf、Y=If 正向曲线',
            filetypes=[('XY 曲线 CSV / JSON','*.csv *.json')])
        if not path:return
        try:
            from simple_curves import read_simple
            data=read_simple(path)
            if data is None:
                from pathlib import Path
                candidate=validate_curve(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            else:
                from simple_curve_ui import import_simple
                candidate=import_simple(self.root,data,'diode',target=caption)
            if candidate is None:return
            data=validate_curve(candidate)
            self._ensure_curve_settings()
            self._diode_curves[target['ref']]=data
            self._curve_sources_changed()
        except (ValueError,OSError,UnicodeError) as exc:
            messagebox.showerror(caption+' 曲线未导入',str(exc),parent=self.root)

