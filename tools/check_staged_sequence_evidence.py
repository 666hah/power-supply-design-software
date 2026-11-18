"""Independently audit the complete RAW from validate_sequence_realistic.py.

This tool never launches a solver or calls the application's analysis function.
All acceptance observations use the original RAW, not report/chart samples.
Passing means the declared scenario behaved as expected, not hardware approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from spice_runtime import TransientRaw, read_log

CASES = ('normal', 'weak_hiccup', 'warm_restart', 'slow_input')
CHUNK = 250_000


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False).encode('utf8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text('utf8'))


def check(checks, name, actual, expected, passed):
    checks.append(dict(name=name, actual=actual, expected=expected, passed=bool(passed)))


def circuit_model_identity(manifest):
    """Compare frozen model bytes, not just unchanged hardware specifications.

    Scenario sources/loads and stop times intentionally differ. The converter
    subcircuits and their namespaced libraries must stay identical, including
    the LDO implementation which has no separate library version string.
    """
    files = {name: row['sha256'] for name, row in manifest.get('files', {}).items()
             if name.endswith(('.lib', '_unit.inc'))}
    if not files:
        raise ValueError('缺少可比较的冻结单元电路/模型')
    return dict(files=files, interconnect=manifest.get('interconnect_model'),
                switching_capacitance_policy=manifest.get('settings', {}).get('include_switching_capacitance'))


def restart_window(manifest):
    """Read the synchronized drop/recovery schedule of this example fixture.

    Require full load before the commanded drop, not merely before eventual
    capacitor discharge/reset. This precondition deliberately rejected the
    earlier 18 ms schedule and must not be weakened to accept that run.
    """
    windows=[]
    for row in manifest.get('sources', {}).values():
        points=row['config'].get('voltage_profile', [])
        down=next((i for i in range(1,len(points)) if points[i]['level']<points[i-1]['level']),None)
        up=next((i for i in range((down or 0)+1,len(points)) if points[i]['level']>points[i-1]['level']),None)
        if down is None or up is None:
            raise ValueError('重启试验缺少明确的掉电及恢复电压时序')
        windows.append((points[down-1]['time_s'],points[up-1]['time_s']))
    if not windows or len(set(windows))!=1:
        raise ValueError('此完整示例验收要求各源同步掉电/恢复，实际时序不一致')
    return windows[0]


def source_capacitor_balance(time, voltage, internal_supply, port_supply, capacitor_current, capacitance, esr):
    """Full-data KCL and integrated charge, avoiding noisy voltage derivatives."""
    charge=0.;maximum_kcl=0.;maximum_ratio=0.;maximum_charge_error=0.
    initial_vc=float(voltage[0])-esr*float(capacitor_current[0])
    minimum_vc=maximum_vc=initial_vc
    for start in range(0,len(time),CHUNK):
        stop=min(len(time),start+CHUNK)
        source=np.asarray(internal_supply[start:stop],dtype=float)
        port=np.asarray(port_supply[start:stop],dtype=float)
        cap=np.asarray(capacitor_current[start:stop],dtype=float)
        error=np.abs(source-port-cap)
        allowance=5e-6+.002*np.maximum.reduce([np.abs(source),np.abs(port),np.abs(cap)])
        maximum_kcl=max(maximum_kcl,float(np.max(error)))
        maximum_ratio=max(maximum_ratio,float(np.max(error/allowance)))
        vc=np.asarray(voltage[start:stop],dtype=float)-esr*cap
        minimum_vc=min(minimum_vc,float(np.min(vc)));maximum_vc=max(maximum_vc,float(np.max(vc)))
        left=max(0,start-1)
        segment=np.asarray(capacitor_current[left:stop],dtype=float)
        increments=np.diff(time[left:stop])*(segment[:-1]+segment[1:])*.5
        integrated=charge+np.r_[0.,np.cumsum(increments)]
        if start:integrated=integrated[1:]
        if len(integrated):charge=float(integrated[-1])
        error_q=integrated-capacitance*(vc-initial_vc)
        maximum_charge_error=max(maximum_charge_error,float(np.max(np.abs(error_q))))
    # RAW uses finite precision; trapezoidal integration across switching edges
    # is checked against 1% of C times the observed capacitor voltage span.
    charge_allowance=max(1e-8,.01*capacitance*max(.1,maximum_vc-minimum_vc))
    return dict(max_kcl_error_A=maximum_kcl,max_kcl_allowance_ratio=maximum_ratio,
        kcl_tolerance='5uA + 0.2% of largest branch current at each full RAW sample',
        capacitor_charge_integral_C=charge,max_charge_residual_C=maximum_charge_error,
        charge_allowance_C=charge_allowance,capacitor_voltage_min_V=minimum_vc,capacitor_voltage_max_V=maximum_vc,
        charge_method='Integral Icap dt = C delta(Vport-ESR*Icap); every original RAW interval; 1% charge-span integration allowance, not hardware margin',
        kcl_passed=maximum_ratio<=1.,charge_passed=maximum_charge_error<=charge_allowance)


def digital_observations(time, values, threshold=.5):
    """Every saved transition, linearly interpolated; no display decimation."""
    state = np.asarray(values) > threshold
    changes = np.flatnonzero(state != np.r_[False, state[:-1]])
    rises, falls = [], []
    for index in changes:
        when = float(time[index])
        if index:
            a, b = float(values[index-1]), float(values[index])
            fraction = np.clip((threshold-a)/(b-a), 0., 1.) if a != b else 1.
            when = float(time[index-1] + fraction*(time[index]-time[index-1]))
        (rises if state[index] else falls).append(when)
    # Each high interval starts at a rise and ends at its following fall, or
    # at the observation boundary. The latter is explicitly right censored.
    ends = falls + ([float(time[-1])] if state[-1] else [])
    return dict(rise_s=rises, fall_s=falls, on_count=len(rises), off_count=len(falls),
        active_time_s=float(sum(end-start for start, end in zip(rises, ends))),
        final_on=bool(state[-1]), right_censored=bool(state[-1]))


def stage_observations(time, values, ready, age, plan):
    indices = np.floor(np.asarray(values)+.5).astype(np.int16)
    if np.any(values < -.01) or np.any(values > len(plan)+.01):
        raise ValueError('阶段探针超出声明索引范围')
    previous = np.r_[0, indices[:-1]]
    changes = np.flatnonzero(indices != previous)
    ready_events = digital_observations(time, ready)
    starts = np.asarray(ready_events['rise_s'])
    entries, resets = [], []
    for index in changes:
        old, stage = int(previous[index]), int(indices[index])
        when = float(time[index])
        if stage == 0:
            resets.append(dict(time_s=when, previous=old, age_s=float(age[index])))
        else:
            pos = np.searchsorted(starts, when, side='right')-1
            ready_since = float(starts[pos]) if pos >= 0 else None
            entries.append(dict(index=stage, name=plan[stage-1]['name'], previous=old,
                time_s=when, ready_since_s=ready_since, ready=bool(ready[index]>.5),
                age_s=float(age[index]), preceding_step_s=float(time[index]-time[index-1]) if index else 0.))
    return dict(entries=entries, resets=resets, ready=ready_events,
        final_index=int(indices[-1]), entry_counts=[sum(e['index']==i for e in entries) for i in range(1,len(plan)+1)],
        restart_count=max(0,sum(e['previous']==0 for e in entries)-1))


def resolve_run(root, name, explicit=None):
    if explicit is not None:
        return Path(explicit).resolve()
    registry = read_json(root/'validation.json') if (root/'validation.json').is_file() else {}
    entry = registry.get('cases', {}).get(name)
    if entry is not None:
        if entry.get('status') not in ('completed','failed','cancelled') or not entry.get('directory'):
            raise ValueError(name+' 尚未在 validation.json 中完成；不替换为历史成功结果')
        run = Path(entry['directory'])
        if run.is_dir():
            return run.resolve()
        # Evidence may have been copied to another computer. Match the exact
        # recorded run name within the requested root, never choose latest.
        moved = root/name/run.name
        if moved.is_dir():
            return moved.resolve()
        raise FileNotFoundError(str(run))
    candidates = [p.parent for p in (root/name).glob('*/result.json')]
    if len(candidates) != 1:
        raise ValueError(f'{name}: 找到 {len(candidates)} 个结果目录，请用 --case-run 明确指定')
    return candidates[0].resolve()


def peak(time, values, sign=1.):
    position = int(np.argmax(values) if sign > 0 else np.argmin(values))
    return dict(value=float(sign*values[position]), time_s=float(time[position]))


def _summary_row(result, group, identity):
    return next((row for row in result.get('summary', {}).get(group, []) if row['id']==identity), {})


def _check_equal_metric(checks, label, raw_value, result_value, tolerance=1e-8):
    good = isinstance(result_value,(int,float)) and abs(raw_value-result_value)<=tolerance
    check(checks,label,dict(raw=raw_value,result=result_value),f'绝对误差≤{tolerance:g}',good)


def active_demand_deviation(time, voltage, age, ready, measured, config):
    """Check actual active current against total R/I/P stage demand and ramps.

    The total-port current intentionally is not compared to this demand: it
    also charges the input capacitor and supplies standby/bleeder branches.
    """
    largest_error,largest_ratio,when=0.,0.,None
    for start in range(0,len(time),CHUNK):
        end=start+CHUNK;v=np.asarray(voltage[start:end],dtype=float)
        clock=np.asarray(age[start:end],dtype=float)-config['delay_s']
        desired=np.zeros_like(v);previous=np.zeros_like(v)
        for stage in config['stages']:
            power=stage['power_W'];mode=stage['mode'];reference=config['nominal_voltage_V']
            if mode=='R':target=np.maximum(v,0.)*power/reference**2
            elif mode=='I':target=np.full_like(v,power/reference)
            else:target=power/np.maximum(v,config['off_V'])
            elapsed=clock-stage['after_s']
            fraction=np.clip(elapsed/stage['ramp_s'],0,1) if stage['ramp_s'] else (elapsed>=0).astype(float)
            desired+=fraction*(target-previous);previous=target
        desired=np.where((ready[start:end]>.5)&(v>0),np.maximum(desired,0.),0.)
        error=np.abs(measured[start:end]-desired)
        ratio=error/(5e-6+.005*np.abs(desired))
        if len(error) and float(np.max(error))>largest_error:
            index=int(np.argmax(error));largest_error=float(error[index]);when=float(time[start+index])
        if len(ratio):largest_ratio=max(largest_ratio,float(np.max(ratio)))
    return dict(max_error_A=largest_error,max_error_time_s=when,max_allowance_ratio=largest_ratio,
        allowance='5uA + 0.5% of instantaneous declared active demand; numerical comparison only')


def _verify_files(run, manifest, result, checks):
    hashes = {}
    for name in ('project.json','manifest.json','result.json','Flyback.log','Flyback.raw'):
        hashes[name] = digest_file(run/name) if (run/name).is_file() else None
    check(checks,'必要证据文件',hashes,'工程、清单、结果、日志和原始RAW均存在',all(hashes.values()))
    mismatches = []
    for name, expected in manifest.get('files',{}).items():
        path = run/name
        if path.parent != run or not path.is_file():
            mismatches.append(name+':缺失或路径异常')
        elif path.stat().st_size != expected['bytes'] or digest_file(path) != expected['sha256']:
            mismatches.append(name+':字节/hash不一致')
    check(checks,'生成电路完整性',mismatches,'manifest.files 中所有电路逐字节一致且非空',not mismatches and bool(manifest.get('files')))
    mismatches = [name for name, expected in result.get('evidence_files',{}).items()
        if Path(name).name != name or not (run/name).is_file() or digest_file(run/name)!=expected]
    check(checks,'结果绑定的证据完整性',mismatches,'result.evidence_files 全部一致且非空',not mismatches and bool(result.get('evidence_files')))
    return hashes


def audit_case(root, name, run):
    checks = []
    answer = dict(case=name,directory=str(run),scope='declared behaviour only; hardware acceptance remains unknown',
        checks=checks,sources={},loads={},hardware_passed=None,normal_startup_passed=None)
    raw = None
    try:
        manifest, result, project = (read_json(run/file) for file in ('manifest.json','result.json','project.json'))
        answer.update(runtime_status=result.get('status'),runtime_failure_reasons=result.get('failure_reasons',[]))
        answer['sha256'] = _verify_files(run,manifest,result,checks)
        check(checks,'本次运行/分析完成',dict(status=result.get('status'),simulation_complete=result.get('simulation_complete'),
            analysis_complete=result.get('analysis_complete'),report_error=result.get('report_error')),
            'completed 且完整仿真/分析，无报告错误；仍不是设计通过',
            result.get('status')=='completed' and result.get('simulation_complete') is True and result.get('analysis_complete') is True and not result.get('report_error'))
        check(checks,'运行已结束','total_elapsed_s' in result,'存在最终运行计时，避免读取报告生成中的中间JSON','total_elapsed_s' in result)
        check(checks,'工程指纹',canonical_hash(project),manifest.get('source_project_sha256'),canonical_hash(project)==manifest.get('source_project_sha256'))
        answer['hardware_sha256'] = canonical_hash([u['spec'] for u in project['units']])
        answer['model_identity'] = circuit_model_identity(manifest)
        answer['model_sha256'] = canonical_hash(answer['model_identity'])
        requested = root/(name+'.json')
        if requested.is_file():
            planned=read_json(requested)
            check(checks,'场景配置未偷换',canonical_hash(project['sequence_config']),canonical_hash(planned['sequence_config']),project['sequence_config']==planned['sequence_config'])
            check(checks,'单元硬件未偷换',answer['hardware_sha256'],canonical_hash([u['spec'] for u in planned['units']]),answer['hardware_sha256']==canonical_hash([u['spec'] for u in planned['units']]))
        else:
            check(checks,'存在冻结场景输入',str(requested),'必须有该场景JSON',False)
        _,log,errors,warnings = read_log(run/'Flyback.log')
        answer.update(log_errors=errors,log_warnings=warnings)
        check(checks,'仿真日志',dict(errors=errors,warnings=warnings),'零错误，零警告；日志另存哈希',not errors and not warnings)
        raw = TransientRaw(run/'Flyback.raw')
        time = raw.time
        stop = float(manifest['settings']['stop_s'])
        step = float(manifest['max_step_s'])
        tolerance_s=max(5*step,1e-7)
        answer['time_domain']=dict(points=len(time),start_s=float(time[0]),end_s=float(time[-1]),expected_end_s=stop,
            maximum_observed_step_s=float(np.max(np.diff(time))),declared_max_step_s=step,event_time_tolerance_s=tolerance_s)
        check(checks,'完整时域',answer['time_domain'],'覆盖0至stop_s，单调且无缺口超过声明步长的数值舍入量',
            time[0]<=1e-12 and abs(time[-1]-stop)<=max(1e-12,stop*1e-6) and np.max(np.diff(time))<=step*1.01+1e-12)
        # Validate every saved probe, not just those selected for graphics.
        nonfinite=[]
        for probe in raw.names:
            values=raw.trace(probe)
            if any(not np.all(np.isfinite(values[i:i+CHUNK])) for i in range(0,len(time),CHUNK)):
                nonfinite.append(probe)
        check(checks,'全部RAW探针有限值',nonfinite,f'{len(raw.names)}条原始探针均有效',not nonfinite)

        for identity,row in manifest['sources'].items():
            config=row['config'];mode=config.get('protection_mode','monitor')
            voltage=raw.trace(row['voltage_probe']);current=raw.trace(row['current_probe'])
            p=peak(time,current,-1.);limit=config.get('current_limit_A')
            info=dict(mode=mode,limit_A=limit,peak_supply_A=p['value'],peak_time_s=p['time_s'],
                peak_reverse_A=max(0.,float(np.max(current))),min_voltage_V=float(np.min(voltage)),
                max_voltage_V=float(np.max(voltage)),final_voltage_V=float(voltage[-1]))
            answer['sources'][identity]=info
            summary=_summary_row(result,'sources',identity)
            _check_equal_metric(checks,identity+'供流峰值复算',max(0.,p['value']),summary.get('supply_current_peak_A'))
            port_probe=row.get('port_current_probe')
            cap_probe=row.get('output_capacitor_current_probe')
            derived_port=not port_probe and row.get('port_current_derivation')=='source-minus-capacitor'
            port_current=raw.trace(port_probe) if port_probe else (-np.asarray(current,dtype=float)-raw.trace(cap_probe) if derived_port else -np.asarray(current,dtype=float))
            port_peak=peak(time,port_current)
            info.update(port_peak_supply_A=max(0.,port_peak['value']),port_peak_time_s=port_peak['time_s'],
                port_reverse_peak_A=max(0.,-float(np.min(port_current))),output_capacitance_F=config.get('output_capacitance_F',0.),
                output_esr_ohm=config.get('output_esr_ohm',0.),port_current_method='direct-probe' if port_probe else 'source-minus-capacitor' if derived_port else 'legacy-internal-probe')
            if port_probe or derived_port:
                _check_equal_metric(checks,identity+'端口供流峰值复算',info['port_peak_supply_A'],summary.get('port_supply_current_peak_A'))
            if config.get('output_capacitance_F',0)>0:
                check(checks,identity+'储能电容端口电流观察契约',dict(port=port_probe,capacitor=cap_probe,derivation=row.get('port_current_derivation')),'内部源与电容探针齐全；端口独立测量或明确 source-minus-capacitor 派生',bool((port_probe or derived_port) and cap_probe))
                if (port_probe or derived_port) and cap_probe:
                    cap_current=raw.trace(cap_probe)
                    balance=source_capacitor_balance(time,voltage,-np.asarray(current,dtype=float),port_current,cap_current,
                        config['output_capacitance_F'],config.get('output_esr_ohm',0.))
                    info['output_capacitor_balance']=balance
                    balance['kcl_independently_observed']=not derived_port
                    if derived_port:
                        balance['kcl_note']='端口电流由KCL组合派生；零残差仅定义恒等式，不计作独立守恒验证。电容电荷积分独立校核。'
                    else:
                        check(checks,identity+'源端电流守恒',balance['max_kcl_error_A'],balance['kcl_tolerance'],balance['kcl_passed'])
                    check(checks,identity+'源端电容电荷守恒',balance['max_charge_residual_C'],dict(allowance_C=balance['charge_allowance_C'],method=balance['charge_method']),balance['charge_passed'])
            check(checks,identity+'不冒称硬件保护合格',summary.get('protection_passed'),'保持未知',summary.get('protection_passed') is None)
            if mode=='monitor':
                check(checks,identity+'实际限流模型',mode,'本次完整示例必须启用主动源模型',False)
                continue
            allowance=max(5e-6,float(limit)*.005)
            info['numerical_peak_allowance_A']=allowance
            check(checks,identity+'实际限流峰值',p['value'],dict(limit_A=limit,numerical_allowance_A=allowance,scope='仅浮点/求解比较容差，非器件降额'),p['value']<=limit+allowance)
            check(checks,identity+'吸流能力',info['peak_reverse_A'],dict(max_reverse_A=limit+allowance if config['sink_current'] else allowance),
                info['peak_reverse_A']<=(limit+allowance if config['sink_current'] else allowance))
            limiting=raw.trace(row['limit_active_probe']);fault=raw.trace(row['fault_probe'])
            info['limiting']=digital_observations(time,limiting)
            info['fault']=digital_observations(time,fault)
            for field in ('limiting','fault'):
                saved=summary.get('limit_state' if field=='limiting' else 'fault_state',{})
                for key in ('on_count','off_count','active_time_s'):
                    _check_equal_metric(checks,identity+' '+field+' '+key,info[field][key],saved.get(key),1e-9)
            if name=='weak_hiccup':
                f=info['fault'];l=info['limiting']
                check(checks,identity+'故障及重试',dict(mode=mode,on=f['on_count'],off=f['off_count']),'hiccup 至少一次故障和一次恢复尝试',mode=='hiccup' and f['on_count']>=1 and f['off_count']>=1)
                naps=[b-a for a,b in zip(f['rise_s'],f['fall_s'])]
                info['complete_hiccup_sleep_s']=naps
                check(checks,identity+'打嗝休眠时间',naps,dict(retry_s=config['retry_s'],tolerance_s=tolerance_s),bool(naps) and all(abs(t-config['retry_s'])<=tolerance_s for t in naps))
                trips=[]
                for when in f['rise_s']:
                    before=[t for t in l['rise_s'] if t<=when]
                    trips.append(None if not before else when-before[-1])
                info['trip_since_last_limit_start_s']=trips
                check(checks,identity+'连续限流后才故障',trips,dict(trip_delay_s=config['trip_delay_s'],tolerance_s=tolerance_s),bool(trips) and all(t is not None and abs(t-config['trip_delay_s'])<=tolerance_s for t in trips))
                stable_fault=fault>.9
                blocked_peak=float(np.max(np.abs(current[stable_fault]))) if np.any(stable_fault) else None
                info['fault_supply_abs_peak_A']=blocked_peak
                check(checks,identity+'休眠实际断流',blocked_peak,dict(max_abs_A=allowance),blocked_peak is not None and blocked_peak<=allowance)

        staged_count=0
        for identity,row in manifest['loads'].items():
            config=row['config'];plan=config.get('stages',[])
            if not plan:continue
            staged_count+=1
            stage=raw.trace(row['stage_probe']);ready=raw.trace(row['ready_probe']);age=raw.trace(row['age_probe'])
            running=raw.trace(row['active_current_probe']);total=raw.trace(row['current_probe']);voltage=raw.trace(row['voltage_probe'])
            observed=stage_observations(time,stage,ready,age,plan)
            info=dict(observed,plan=plan,delay_s=config['delay_s'],ready_conditions=config['ready_conditions'],
                active_current_peak_A=float(np.max(running)),total_current_peak_A=float(np.max(total)),
                min_voltage_V=float(np.min(voltage)),final_voltage_V=float(voltage[-1]))
            answer['loads'][identity]=info
            info['active_demand_comparison']=active_demand_deviation(time,voltage,age,ready,running,config)
            check(checks,identity+'实际分阶段耗流',info['active_demand_comparison'],'运行电流符合声明R/I/P与阶段总量及过渡斜率',info['active_demand_comparison']['max_allowance_ratio']<=1.)
            summary=_summary_row(result,'loads',identity)
            for key in ('active_current_peak_A','current_peak_A'):
                independent=info['total_current_peak_A' if key=='current_peak_A' else key]
                _check_equal_metric(checks,identity+' '+key,independent,summary.get(key))
            saved=summary.get('stage_observations',{})
            _check_equal_metric(checks,identity+'复位计数复算',len(info['resets']),saved.get('reset_count'))
            for i,count in enumerate(info['entry_counts'],1):
                saved_stage=next((s for s in saved.get('stages',[]) if s['index']==i),{})
                _check_equal_metric(checks,identity+f'阶段{i}次数复算',count,saved_stage.get('entry_count'))
            relative=[]
            for entry in info['entries']:
                target=config['delay_s']+plan[entry['index']-1]['after_s']
                delta=entry['age_s']-target
                clock_error=None if entry['ready_since_s'] is None else entry['age_s']-(entry['time_s']-entry['ready_since_s'])
                relative.append(dict(stage=entry['index'],time_s=entry['time_s'],age_s=entry['age_s'],target_age_s=target,
                    entry_error_s=delta,age_vs_ready_elapsed_error_s=clock_error,ready=entry['ready']))
            info['relative_entry_timing']=relative
            # An empty fault-case list is valid: no stages should be invented.
            check(checks,identity+'阶段按连续就绪相对计时',relative,dict(tolerance_s=tolerance_s,scope='delay_s + after_s，非全局绝对时间'),
                all(e['ready'] and abs(e['entry_error_s'])<=tolerance_s and e['age_vs_ready_elapsed_error_s'] is not None and abs(e['age_vs_ready_elapsed_error_s'])<=tolerance_s for e in relative))
            conditions=[dict(port=identity,on_V=config['on_V'],off_V=config['off_V'],probe=row['voltage_probe'])]
            conditions += [dict(c,probe=manifest['ports'][c['port']]['voltage_probe']) for c in config['ready_conditions']]
            condition_evidence=[]
            for c in conditions:
                v=raw.trace(c['probe']);on=float(c['on_V']);off=float(c['off_V'])
                # An asserted hysteretic condition must be above its off
                # threshold, and must have reached on at some earlier sample.
                # Inspect every ready interval, allowing only solver-edge dt.
                for start,end in zip(info['ready']['rise_s'],info['ready']['fall_s']+([float(time[-1])] if info['ready']['final_on'] else [])):
                    left=int(np.searchsorted(time,start+tolerance_s));right=int(np.searchsorted(time,end-tolerance_s))
                    minimum=float(np.min(v[left:right])) if right>left else None
                    prefix=v[:min(len(time),left+1)]
                    prefix_peak=float(np.max(prefix))
                    on_hits=np.flatnonzero(prefix>=on-1e-4);off_hits=np.flatnonzero(prefix<off-1e-4)
                    latched_on=bool(len(on_hits) and (not len(off_hits) or on_hits[-1]>off_hits[-1]))
                    ok=latched_on and (minimum is None or minimum>=off-1e-4)
                    condition_evidence.append(dict(port=c['port'],ready_start_s=start,ready_end_s=end,min_while_ready_V=minimum,
                        observed_prior_max_V=prefix_peak,latched_on_after_latest_reset=latched_on,on_V=on,off_V=off,passed=ok))
            info['condition_evidence']=condition_evidence
            check(checks,identity+'就绪期间实际电压',condition_evidence,'各条件均曾达到on且就绪期未低于off，边沿外检查',all(c['passed'] for c in condition_evidence))
            if name in ('normal','slow_input'):
                check(checks,identity+'所有阶段到达',info['entry_counts'],'每个声明阶段至少实际到达一次',all(c>=1 for c in info['entry_counts']))
                # Planned shutdown is excluded from the no-reset operating window.
                first_off=min(c['off_s'] for c in manifest['configuration']['sources'].values())
                early_resets=[e for e in info['resets'] if e['time_s']<first_off]
                check(checks,identity+'关机前没有意外复位',early_resets,f'首个源计划掉电{first_off:g}s前无复位',not early_resets)
            if name=='warm_restart':
                drop_s,recovery_s=restart_window(manifest)
                reset=[e for e in info['resets'] if drop_s<=e['time_s']<recovery_s]
                first=[e for e in info['entries'] if e['index']==1 and e['time_s']>recovery_s]
                final=[e for e in info['entries'] if e['index']==len(plan) and e['time_s']>recovery_s]
                before=[e for e in info['entries'] if e['index']==len(plan) and e['time_s']<drop_s]
                check(checks,identity+'断电复位后重新完成启动',dict(prior_final=before,gap_resets=reset,restarted_stage1=first,restarted_final=final),
                    f'{drop_s*1000:g}ms前到末阶段，{drop_s*1000:g}–{recovery_s*1000:g}ms实际复位，{recovery_s*1000:g}ms后从stage1重计时并再次到末阶段',bool(before and reset and first and final))
                info['restart_residual_voltage_V']=float(voltage[min(len(time)-1,int(np.searchsorted(time,recovery_s)))])
        check(checks,'完整三路真实负载',staged_count,'恰好3个有阶段计划的负载',staged_count==3)
        if name=='weak_hiccup':
            finals={key:val['entry_counts'][-1] for key,val in answer['loads'].items()}
            check(checks,'弱源未冒充正常启动',finals,'此故障注入下三路均未到全部运行阶段',all(value==0 for value in finals.values()))
        answer['limitations']=[
            '本验收仅针对声明的行为模型与冻结电路，不代表原厂芯片、实际板卡或硬件安全通过。',
            '事件来自完整离散RAW，计数为可观察下界；未保存的窄事件不能据此排除。',
            '电流峰值由所有RAW样本统计；图表缩点不参与验收。',
            '阶段时间容差为5个声明最大步长或100ns，用于数值事件比较，不改变原始波形。',
            '源电流数值比较容差为额定限流的0.5%或5µA，未将此值当作真实器件能力。',
            '不将故障释放次数等同于下游启动成功；总端口电流含电容/待机，运行电流单列。']
    except Exception as exc:
        answer['error']=f'{type(exc).__name__}: {exc}'
        check(checks,'完整证据可读取',answer['error'],'存在且完整的本次RAW/manifest/result',False)
    finally:
        if raw is not None:raw.close()
    passed=bool(checks) and all(row['passed'] for row in checks)
    answer['scenario_expectations_met']=passed
    if name=='weak_hiccup':
        answer['conclusion']='符合故障预期' if passed else '故障预期未全部证实'
    else:
        answer['normal_startup_passed']=passed
        answer['conclusion']='声明场景检查通过（非硬件验收）' if passed else '声明场景检查未通过'
    return answer


def audit(root, names=CASES, explicit=None):
    root=Path(root).resolve();explicit=explicit or {}
    receipt=dict(schema='power.staged-sequence-independent-evidence/1',
        created_utc=datetime.now(timezone.utc).isoformat(),root=str(root),
        method='full original RAW; independent of application analyzer; no solver run',cases={},checks=[],hardware_passed=None)
    for name in names:
        try:run=resolve_run(root,name,explicit.get(name))
        except Exception as exc:
            receipt['cases'][name]=dict(case=name,scenario_expectations_met=False,conclusion='本次证据未就绪',error=str(exc));continue
        receipt['cases'][name]=audit_case(root,name,run)
    hashes={name:c.get('hardware_sha256') for name,c in receipt['cases'].items()}
    check(receipt['checks'],'各场景沿用同一单元硬件',hashes,'所有选中场景有相同硬件指纹',all(hashes.values()) and len(set(hashes.values()))==1)
    model_hashes={name:c.get('model_sha256') for name,c in receipt['cases'].items()}
    check(receipt['checks'],'各场景沿用同一仿真模型',model_hashes,
        '所有选中场景的冻结单元电路、模型库及连接模型一致；不混用修正前后结果',
        all(model_hashes.values()) and len(set(model_hashes.values()))==1)
    if 'normal' in names and 'slow_input' in names:
        a=receipt['cases']['normal'].get('loads',{});b=receipt['cases']['slow_input'].get('loads',{})
        comparisons=[]
        for identity in sorted(set(a)|set(b)):
            av=a.get(identity,{}).get('entries',[]);bv=b.get(identity,{}).get('entries',[])
            old=next((e['time_s'] for e in av if e['index']==1),None)
            new=next((e['time_s'] for e in bv if e['index']==1),None)
            comparisons.append(dict(id=identity,normal_first_stage_s=old,slow_first_stage_s=new,delta_s=None if old is None or new is None else new-old,
                passed=old is not None and new is not None and new>old))
        check(receipt['checks'],'慢上升依实际电压延后启动',comparisons,'三负载的stage1均较正常上升晚；各自仍满足相对就绪计时',len(comparisons)==3 and all(c['passed'] for c in comparisons))
    receipt['all_selected_expectations_met']=all(c['scenario_expectations_met'] for c in receipt['cases'].values()) and all(c['passed'] for c in receipt['checks'])
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'output/完整分阶段电源树验证_20261111')
    parser.add_argument('--cases',nargs='+',choices=CASES,default=list(CASES))
    parser.add_argument('--case-run',action='append',default=[],metavar='CASE=RUN_DIRECTORY',help='明确选择某次运行，不自动采用历史成功结果')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/sequence-staged-independent-audit.json')
    args=parser.parse_args(argv);explicit={}
    for item in args.case_run:
        key,separator,path=item.partition('=')
        if not separator or key not in args.cases:parser.error('--case-run 应为已选择的CASE=RUN_DIRECTORY')
        explicit[key]=path
    result=audit(args.input,args.cases,explicit)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(output=str(args.output.resolve()),all_selected_expectations_met=result['all_selected_expectations_met'],
        cases={name:case['conclusion'] for name,case in result['cases'].items()}),ensure_ascii=False,indent=2))
    return 0 if result['all_selected_expectations_met'] else 1


if __name__=='__main__':
    raise SystemExit(main())
