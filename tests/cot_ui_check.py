"""Actual Tk editor, shared-schema and project-persistence smoke checks."""
import copy
import json
import os
from pathlib import Path
import sys
import time
if sys.platform=='win32':
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'artifacts/cot-ui-20261115/mpl'))
import tkinter as tk
import main


def ready(app, predicate=lambda row:True):
    end=time.monotonic()+30
    while time.monotonic()<end:
        app.root.update()
        if app._snapshot_valid and app._last and predicate(app._last):return app._last
        time.sleep(.02)
    raise AssertionError(app.status_var.get())


def run():
    out=ROOT/'artifacts/cot-ui-20261115';out.mkdir(exist_ok=True,parents=True)
    sample=json.loads((ROOT/'examples/96W_BUCK_COT_4PH.json').read_text('utf-8'))
    root=tk.Tk();root.geometry('1460x960');root.attributes('-alpha',0)
    errors=[];root.report_callback_exception=lambda kind,error,tb:errors.append(repr(error))
    app=main.PowerSupplyAnalyzer(root,initial_config=sample,on_return=lambda _:None)
    editor=None
    try:
        ready(app)
        editor=app._open_cot_settings();root.update()
        assert editor is not None and editor.window.grab_current() is None
        assert editor.collect()['phase_parameters']==sample['cot_config']['phase_parameters']
        editor.variables['source_rise_s'][0].set('1.2')
        editor.phase_table.selection_set('1');root.update()
        editor.phase_variables['sense_offset_A'].set('0.12')
        editor.update_phase();root.update();editor.apply()
        ready(app,lambda r:r['p']['cot_config']['source_rise_s']==.0012)
        saved=app._config_dict()
        assert saved['cot_config']['phase_parameters'][1]['sense_offset_A']==.12
        assert saved['cot_config']['source_rise_s']==.0012
        assert saved['cot_config']['model']=='current_feedback'
        # Bounds are rejected by the shared contract, with no silent truncation.
        bad=copy.deepcopy(saved['cot_config']);bad['phase_parameters'].pop()
        from cot_settings import configuration
        try:configuration(dict(app.get_params(),cot_config=bad))
        except ValueError:pass
        else:raise AssertionError('phase length accepted')
        editor.variables['acceptance.recovery_s'][0].set('0')
        try:editor.collect()
        except ValueError:pass
        else:raise AssertionError('zero recovery accepted')
        editor.variables['acceptance.recovery_s'][0].set('1')
        # Capture the actual rendered dialog, including all five tabs.
        from PIL import ImageGrab
        editor.window.attributes('-alpha',1);editor.window.lift()
        for i in range(len(editor.tabs.tabs())):
            editor.tabs.select(i);root.update();time.sleep(.1)
            x,y=editor.window.winfo_rootx(),editor.window.winfo_rooty()
            ImageGrab.grab((x,y,x+editor.window.winfo_width(),y+editor.window.winfo_height())).save(out/f'tab-{i+1}.png')
        editor.window.destroy();editor=None
        app.load_isolated_example('24W_BUCK_VM_TPS40200.json');ready(app,lambda r:not r['op'].get('cot'))
        app._apply_config(saved);ready(app,lambda r:r['op'].get('cot') is not None)
        assert app.get_params()['cot_config']==saved['cot_config']
        assert not errors,errors
        receipt=dict(tabs=5,nonmodal=True,saved_roundtrip=True,validation=True,callback_errors=errors)
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps(receipt))
    finally:
        if editor:editor.window.destroy()
        app._calculation_worker.close();root.destroy()


if __name__=='__main__':run()
