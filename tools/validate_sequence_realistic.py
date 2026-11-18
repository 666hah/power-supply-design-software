"""Build and verify an independent staged-load power tree with real LTspice.

No user profile is read or written. Scenario expectations are observations of
declared behavior models, never certification of the reference ICs or hardware.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

BASE = ROOT / 'examples/SYSTEM_STARTUP_SHUTDOWN.json'
DEST = ROOT / 'examples/SYSTEM_STAGED_STARTUP.json'


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')


def stage(name, after, power, *, mode='I', ramp=.00025):
    return dict(name=name, after_s=after, mode=mode, power_W=power, ramp_s=ramp)


def condition(port, on, off):
    return dict(port=port, on_V=on, off_V=off)


def build_project():
    from power_network import normalize
    from system_sequence_config import normalize as sequence_config
    p = json.loads(BASE.read_text('utf8'))
    p.update(title='完整示例：真实限流与控制板分阶段联合启停', revision='B')
    c = p['sequence_config']
    c['settings'].update(stop_s=.045, timeout_s=300., threads=2)
    for row in c['units'].values():
        row['disable_s'] = .05
    # Keep the original converter hardware and its explicitly approximate
    # reference silicon model. External source protection is now electrical.
    c['sources']['BUS-MAIN'].update(protection_mode='cc', current_limit_A=2.,
        on_s=0., rise_s=.002, off_s=.027, fall_s=.001, voltage_profile=[])
    c['sources']['BUS-BACKUP'].update(protection_mode='cc', current_limit_A=1.,
        on_s=0., rise_s=.002, off_s=.038, fall_s=.001, voltage_profile=[])
    # Explicit external-supply energy store, after its limiter/blocking path.
    # These are engineering assumptions, not measured source capacitors. The
    # converters retain their own Cin, and all scenarios use the same source C.
    for row in c['sources'].values():
        row.update(output_capacitance_F=10e-6,output_esr_ohm=.1)
    c['units']['PSU-12V']['disable_s'] = .029
    c['units']['PSU-5V']['disable_s'] = .041
    c['units']['LDO-3V3']['disable_s'] = .041
    load = {row['id']: row for row in p['loads']}
    load['LOAD-3V3']['name'] = '控制板MCU 3.3V电源脚'
    load['LOAD-5V']['name'] = '控制板通信与采样5V电源脚'
    load['LOAD-OR']['name'] = '驱动模块母线端口 等效分阶段耗功'
    c['loads']['LOAD-3V3'].update(mode='I', power_W=.165, nominal_voltage_V=3.3,
        on_V=3.05, off_V=2.75, off_current_A=.002, delay_s=.0005,
        ready_conditions=[condition('PSU-5V/OUT1',4.65,4.35)],
        stages=[stage('MCU复位释放与引导',0,.0396),
                stage('固件初始化与通信',.003,.1155),
                stage('正常运行',.006,.165)])
    c['loads']['LOAD-5V'].update(mode='I', power_W=2., nominal_voltage_V=5.,
        on_V=4.65, off_V=4.35, off_current_A=.005, delay_s=.001,
        input_capacitance_F=47e-6,
        ready_conditions=[condition('LDO-3V3/OUT1',3.05,2.75)],
        stages=[stage('外设待命',0,.4), stage('采样与通信启动',.003,1.),
                stage('全部外设运行',.008,2.)])
    c['loads']['LOAD-OR'].update(mode='P', power_W=3., nominal_voltage_V=11.5,
        on_V=10.6, off_V=9.5, off_current_A=.001, delay_s=.003,
        ready_conditions=[condition('LDO-3V3/OUT1',3.05,2.75),
                          condition('PSU-5V/OUT1',4.65,4.35)],
        stages=[stage('驱动待机',0,.15,mode='P'),
                stage('PWM投入 等效端口功率',.007,3.,mode='P',ramp=.001)])
    # Remove old scenario-only claims from metadata; keep reference hardware
    # evidence and all explicit limitations about the actual IC implementations.
    for unit in p['units']:
        metadata = unit['spec'].get('__sequence_example',{})
        metadata['assumptions'] = [s for s in metadata.get('assumptions',[])
            if not any(token in s for token in ('本例2A/1A','主源22ms','后Buck等待OR','主/备输入保留'))]
        metadata['validation_status'] = '本例硬件沿用前版；当前仿真证据以本轮run目录及验收记录为准。'
    p['sequence_config'] = sequence_config(p)
    p = normalize(p)
    return p


CASE_NOTES = {
    'normal': '正常双源上电，真实CC限流，控制板分阶段运行，主备切换及关机。',
    'weak_hiccup': '故障注入：主备可用供流降至40/30mA且连续限流0.7ms后休眠3ms；不是正常电源额定值。',
    'warm_restart': '两源22ms开始掉电、32ms恢复；先让全部负载完成首次投入，再观察同次瞬态的电容残压、掉压复位及重新计时。',
    'slow_input': '两个输入源以8ms上升；板卡负载跟随实际就绪条件，不固定使用冷启动绝对时刻。',
}


def scenario(base, name):
    p = copy.deepcopy(base)
    p['title'] += ' · ' + name
    c = p['sequence_config']
    if name == 'weak_hiccup':
        c['settings']['stop_s'] = .025
        for identity, limit in [('BUS-MAIN',.04),('BUS-BACKUP',.03)]:
            c['sources'][identity].update(protection_mode='hiccup',current_limit_A=limit,
                trip_delay_s=.0007,retry_s=.003,off_s=.03)
    elif name == 'warm_restart':
        c['settings']['stop_s'] = .060
        for row in c['units'].values(): row['disable_s'] = .065
        for row in c['sources'].values():
            row['voltage_profile'] = [dict(time_s=t,level=v) for t,v in
                [(0,0),(.002,1),(.022,1),(.0225,0),(.032,0),(.034,1),(.060,1)]]
    elif name == 'slow_input':
        for row in c['sources'].values(): row['rise_s'] = .008
    elif name != 'normal':
        raise ValueError(name)
    return p


def hardware_digest(project):
    return hashlib.sha256(json.dumps([u['spec'] for u in project['units']],
        ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf8')).hexdigest()


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--run',action='store_true',help='实际执行LTspice，默认只生成JSON和编译检查')
    a.add_argument('--cases',nargs='+',choices=list(CASE_NOTES),default=list(CASE_NOTES))
    a.add_argument('--output',type=Path,default=ROOT/'output/完整分阶段电源树验证_20261111')
    a.add_argument('--cancel-file',type=Path,help='出现此文件时取消本工具拥有的仿真，保留诊断证据')
    args = a.parse_args(argv)
    project = build_project()
    dump(DEST,project)
    dump(args.output/'完整分阶段电源树示例.json',project)
    from system_sequence_export import project_files
    _,manifest = project_files(project)
    receipt = dict(schema='power.sequence-staged-validation/1',scope='independent engineering example; not hardware validation',
        source_example_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
        hardware_sha256=hardware_digest(project),compile=dict(sources=len(manifest['sources']),
        units=len(manifest['units']),loads=len(manifest['loads'])),cases={})
    previous_path = args.output/'validation.json'
    if previous_path.is_file():
        previous = json.loads(previous_path.read_text('utf8'))
        if (previous.get('hardware_sha256') == receipt['hardware_sha256'] and
                previous.get('source_example_sha256') == receipt['source_example_sha256']):
            receipt['cases'] = previous.get('cases',{})
    dump(args.output/'validation.json',receipt)
    for name in args.cases:
        case = scenario(project,name)
        assert hardware_digest(case)==receipt['hardware_sha256']
        dump(args.output/(name+'.json'),case)
        entry = dict(description=CASE_NOTES[name],status='not_run',hardware_sha256=hardware_digest(case))
        if name in receipt['cases']:
            prior = receipt['cases'][name]
            entry['prior_attempts'] = prior.get('prior_attempts',[])+[
                {k:prior[k] for k in ('status','directory','result_path','wall_s') if k in prior}]
        receipt['cases'][name] = entry
        dump(args.output/'validation.json',receipt)
        if args.run:
            from system_sequence_runtime import run
            started = time.monotonic()
            result = run(case,args.output/name,
                cancelled=lambda: bool(args.cancel_file and args.cancel_file.exists()),
                progress=lambda m: print(name+': '+m,flush=True))
            entry.update(result,wall_s=time.monotonic()-started)
            dump(args.output/'validation.json',receipt)
    print(json.dumps({k:{key:value for key,value in v.items() if key in
        ('status','directory','word_path','report_error','wall_s')} for k,v in receipt['cases'].items()},
        ensure_ascii=False,indent=2),flush=True)
    return 0 if all(x['status'] in ('not_run','completed') and not x.get('report_error') for x in receipt['cases'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
