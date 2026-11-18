"""Independent real LTspice validation of source and board-load behaviours."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from system_sequence_behavior_check import sample
import power_network
from system_sequence_config import normalize
from system_sequence_export import export_project
from spice_runtime import _run,find_ltspice,TransientRaw,read_log


def build():
    p=sample()
    for name in ('CC','FOLD','HICCUP'):
        p['sources'].append(dict(id=name,name=name,min=12.,max=12.,capacity=12.,enabled=True))
        p['loads'].append(dict(id=name+'-LOAD',name=name+'-LOAD',power=144.,min=0.,max=20.,enabled=True))
        p['connections'].append(dict(id='E-'+name,source=dict(kind='bus',id=name,output=1),target=name+'-LOAD',mode='direct',vf=0.,enabled=True))
    p=power_network.normalize(p);c=normalize(p);p['sequence_config']=c
    c['settings'].update(stop_s=.020,max_step_s=2e-6)
    for name,mode in [('CC','cc'),('FOLD','foldback'),('HICCUP','hiccup')]:
        c['sources'][name].update(protection_mode=mode,current_limit_A=1.,foldback_short_A=.2,
            trip_delay_s=.001,retry_s=.003,voltage_profile=[dict(time_s=t,level=v) for t,v in
                [(0,0),(.0001,1),(.0081,1),(.0082,0),(.011,0),(.0111,1)]])
        c['loads'][name+'-LOAD'].update(delay_s=0.,ramp_s=0.,input_capacitance_F=20e-6,input_esr_ohm=.1)
    c['sources']['SRC'].update(sink_current=True,rise_s=.0001,off_s=.021)
    c['sources']['PG'].update(sink_current=True,voltage_profile=[dict(time_s=t,level=v) for t,v in
        [(0,0),(.0019,0),(.002,1),(.009,1),(.0091,0),(.0119,0),(.012,1)]])
    c['loads']['LOAD'].update(mode='I',nominal_voltage_V=5.,on_V=4.2,off_V=3.8,delay_s=.001,off_current_A=.001,
        stages=[dict(name='boot',after_s=0.,mode='I',power_W=.5,ramp_s=.0002),
                dict(name='run',after_s=.003,mode='I',power_W=1.5,ramp_s=.0002)],
        ready_conditions=[dict(port='PG',on_V=3.,off_V=2.7)],input_capacitance_F=47e-6)
    return p


def main():
    folder=ROOT/'artifacts/sequence-v2-core/live';folder.mkdir(parents=True,exist_ok=True)
    manifest=export_project(build(),folder)
    wall=_run(find_ltspice(),folder,90,lambda:False)
    _,log,errors,warnings=read_log(folder/'Flyback.log')
    assert not errors and not warnings,(errors,warnings)
    raw=TransientRaw(folder/'Flyback.raw');t=raw.time
    def at(probe,when):return float(np.interp(when,t,raw.trace(probe)))
    def interval(probe,a,b):return np.asarray(raw.trace(probe)[(t>=a)&(t<=b)])
    receipt=dict(scope='actual-LTspice-behavior-fixture; not hardware validation',wall_s=wall,
                 end_s=float(t[-1]),points=len(t),errors=errors,warnings=warnings,sources={},load={})
    assert t[-1]>=.020*(1-1e-6)
    for name in ('CC','FOLD','HICCUP'):
        row=manifest['sources'][name];cur=-raw.trace(row['current_probe'])
        receipt['sources'][name]=dict(peak_A=float(np.max(cur)),mean_steady_A=float(np.mean(cur[(t>.001)&(t<.00105)])),
            voltage_V=at(row['voltage_probe'],.003),fault_max=float(np.max(raw.trace(row['fault_probe']))))
        assert float(np.max(cur))<=1.001
    assert abs(receipt['sources']['CC']['voltage_V']-1.01)<.004
    # Source node includes the explicitly exported 10 mOhm interconnect.
    expected=.2*1.01/(1-.8*1.01/12)
    assert abs(receipt['sources']['FOLD']['voltage_V']-expected)<.004
    hc=manifest['sources']['HICCUP'];fault=np.asarray(raw.trace(hc['fault_probe']))>.5
    rises=t[1:][np.diff(fault.astype(int))==1];falls=t[1:][np.diff(fault.astype(int))==-1]
    receipt['sources']['HICCUP'].update(fault_rises_s=rises.tolist(),fault_falls_s=falls.tolist())
    assert len(rises)>=4
    assert np.max(interval(hc['fault_probe'],.009,.010))<.01
    assert np.max(np.abs(interval(hc['current_probe'],.002,.003)))<1e-6
    for start in rises:
        end=falls[falls>start]
        if len(end) and not .0081<end[0]<.0083:assert abs(float(end[0]-start)-.003)<5e-6
    row=manifest['loads']['LOAD']
    for when,expected in [(.0048,.1),(.0078,.3),(.010,0.),(.014,.1),(.017,.3)]:
        got=at(row['active_current_probe'],when)
        receipt['load'][str(when)]=dict(active_A=got,stage=at(row['stage_probe'],when),ready=at(row['ready_probe'],when))
        assert abs(got-expected)<1e-4,(when,got,expected)
    assert at(row['stage_probe'],.010)<.01
    assert abs(at(row['current_probe'],.010)-.001)<1e-5
    raw.close()
    (folder/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
