"""Owned LTspice batch runs, bounded RAW reading and auditable comparisons."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Event, Lock
import time
import zipfile
import numpy as np


def find_ltspice():
    candidates=[os.environ.get('LTSPICE_EXE',''),r'D:\LTSPCIE\LTspice.exe',
        r'C:\Program Files\ADI\LTspice\LTspice.exe',r'C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Programs\ADI\LTspice\LTspice.exe')]
    preferences=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'PowerDesign'/'ltspice.json'
    try:candidates.insert(0,json.loads(preferences.read_text(encoding='utf-8'))['executable'])
    except (OSError,ValueError,KeyError,TypeError):pass
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()),None)


def set_ltspice(executable):
    path=Path(executable).resolve()
    if path.name.casefold() not in ('ltspice.exe','xviix64.exe','xviix86.exe') or not path.is_file():
        raise ValueError('请选择实际的 LTspice.exe 或 XVIIx64.exe')
    preferences=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'PowerDesign'/'ltspice.json'
    preferences.parent.mkdir(parents=True,exist_ok=True)
    preferences.write_text(json.dumps(dict(executable=str(path)),ensure_ascii=False),encoding='utf-8')


def endpoint_workers(endpoint_count, threads, *, parallel=True):
    """Allow at most two solvers with capacity left for the UI and OS."""
    cpu_count = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    if parallel and endpoint_count > 1 and cpu_count >= max(6, 2 * int(threads) + 2):
        return 2
    return 1


def run_endpoint_cases(cases, solve, *, workers, cancelled, progress, stages_per_case, total):
    """Run isolated endpoint pipelines and collect their results in input order."""
    from calculation_scheduler import CalculationCancelled

    stopped = Event()
    progress_lock = Lock()
    stages = [0] * len(cases)

    def interrupted():
        return stopped.is_set() or cancelled()

    def execute(index, case):
        if interrupted():
            raise CalculationCancelled()

        def notify(stage, message):
            if progress is None:
                return
            with progress_lock:
                stages[index] = max(stages[index], stage)
                label = f'{workers} 端点并行 · {message}' if workers > 1 else message
                progress(sum(stages), total, label)

        result = solve(case, interrupted, notify)
        with progress_lock:
            stages[index] = stages_per_case
        if interrupted():
            raise CalculationCancelled()
        return result

    if workers == 1:
        return [execute(index, case) for index, case in enumerate(cases)]

    results = [None] * len(cases)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='spice-endpoint') as pool:
        pending = {pool.submit(execute, index, case): index for index, case in enumerate(cases)}
        try:
            for future in as_completed(pending):
                results[pending[future]] = future.result()
        finally:
            stopped.set()
            for future in pending:
                future.cancel()
    return results


def read_log(path):
    data=Path(path).read_bytes()
    text=data.decode('utf-16') if data.startswith((b'\xff\xfe',b'\xfe\xff')) else data.decode('utf-8',errors='replace')
    measurements={m[1]:float(m[2]) for m in re.finditer(r'(?m)^([a-z]\w*)(?::\s+.*?|\s*)=([-+\d.eE]+)(?:\s|$)',text)}
    errors=[line.strip() for line in text.splitlines() if any(x in line.lower() for x in ('fatal error','timestep too small','singular matrix','measurement failed','voltage not found','current not found'))]
    warnings=[line.strip() for line in text.splitlines() if line.lower().startswith('warning:')]
    return measurements,text,errors,warnings


class TransientRaw:
    """LTspice real forward binary only, with validated lengths and time axis."""
    def __init__(self,path):
        path=Path(path)
        with path.open('rb') as stream:header_bytes=stream.read(65536)
        encoding='utf-16-le' if header_bytes.startswith(b'T\x00') else 'utf-8'
        marker='Binary:\n'.encode(encoding)
        where=header_bytes.find(marker)
        if where<0:raise ValueError('RAW 格式不是受支持的二进制瞬态数据')
        header=header_bytes[:where].decode(encoding)
        flags=re.search(r'^Flags:\s*(.*)$',header,re.M)[1].strip().split()
        if 'real' not in flags or 'FastAccess' in flags or 'complex' in flags:
            raise ValueError('当前读取器只支持普通 real 瞬态 RAW，请关闭 FastAccess 后重跑')
        count=int(re.search(r'No\. Variables:\s*(\d+)',header)[1]);points=int(re.search(r'No\. Points:\s*(\d+)',header)[1])
        # Long terminal-only tests save far fewer channels than detailed
        # device runs. Keep their original switching samples within a separate
        # time-axis budget so a completed uncompressed test can be measured.
        point_limit=80000000 if 2<=count<=10 else 30000000
        if not 2<=points<=point_limit:raise ValueError('RAW 点数无效或超过可用预算，请缩短仿真时长')
        names=[m[1].casefold() for m in re.finditer(r'^\s*\d+\s+(\S+)\s+\S+\s*$',header.rsplit('Variables:',1)[1],re.M)]
        dtype=np.dtype([('time','<f8'),('values','<f8' if 'double' in flags else '<f4',(count-1,))])
        offset=where+len(marker)
        if len(names)!=count or path.stat().st_size!=offset+points*dtype.itemsize:raise ValueError('RAW 不完整或头信息与数据长度不一致')
        self.data=np.memmap(path,mode='r',dtype=dtype,offset=offset,shape=(points,))
        self.names={name:i-1 for i,name in enumerate(names) if i}
        self.time=np.abs(self.data['time'])  # LTspice marks breakpoints with negative time
        for first in range(0,points,500000):
            chunk=self.time[max(0,first-1):first+500000]
            if not np.all(np.isfinite(chunk)) or np.any(np.diff(chunk)<0):raise ValueError('RAW 时间倒退，可能包含多个 .step，请逐工况运行')
    def trace(self,name):return self.data['values'][:,self.names[name.casefold()]]
    def samples(self,names,start,end,points=2400):
        if points is None:
            # Short QR windows contain narrow real commutation pulses. Keep
            # every original point so the displayed peak matches metrology.
            a,b=np.searchsorted(self.time,[start,end])
            inside=self.time[a:b]
            axis=np.r_[start,inside[(inside>start)&(inside<end)],end]
        else:
            axis=np.linspace(start,end,points)
        return TransientRaw._samples_at(self,names,axis)
    def _samples_at(self,names,axis):
        neighbours=np.searchsorted(self.time,axis,side='right')
        right=np.clip(neighbours,0,len(self.time)-1)
        left=np.clip(neighbours-1,0,len(self.time)-1)
        width=self.time[right]-self.time[left]
        fraction=np.divide(axis-self.time[left],width,out=np.zeros_like(axis),where=width>0)
        fraction=np.clip(fraction,0,1)
        # Gather only the neighbouring points needed by each displayed sample.
        # np.interp on a strided float32 memmap makes whole-file float64 copies.
        result=dict(time=axis.tolist())
        for key in names:
            values=self.trace(key);a=values[left].astype(float);b=values[right].astype(float)
            result[key]=(a+(b-a)*fraction).tolist()
        return result
    def plot_samples(self,signals,start,end,bins=650,markers=()):
        """Keep each plotted signal's extrema from each time bin, plus event edges."""
        edges=np.searchsorted(self.time,np.linspace(start,end,bins+1))
        indices=[]
        for positive,negative in signals.values():
            values=self.trace(positive)
            reference=self.trace(negative) if negative else None
            for first,last in zip(edges[:-1],edges[1:]):
                if first==last:continue
                segment=values[first:last]
                if reference is not None:
                    segment=segment.astype(float)-reference[first:last]
                indices.extend((first+int(np.argmin(segment)),first+int(np.argmax(segment))))
        bounds=[start,end]+[t for t in markers if start<=t<=end]
        indices=np.unique(indices).astype(int)
        exact_time=self.time[indices]
        marker_time=np.setdiff1d(bounds,exact_time)
        names=dict.fromkeys(node for terminals in signals.values() for node in terminals if node)
        interpolated=self._samples_at(names,marker_time)
        times=np.r_[exact_time,marker_time]
        order=np.argsort(times,kind='stable')
        samples={node:np.r_[self.trace(node)[indices].astype(float),interpolated[node]][order] for node in names}
        result=dict(time=times[order].tolist())
        for name,(positive,negative) in signals.items():
            result[name]=(samples[positive]-samples[negative] if negative else samples[positive]).tolist()
        return result
    def close(self):
        self.time=None
        self.data._mmap.close()


def partial_transient_time(path):
    """Read an unfinished RAW tail for diagnostics only, never measurements."""
    import struct
    try:
        with Path(path).open('rb') as stream:
            header_bytes=stream.read(65536)
            encoding='utf-16-le' if header_bytes.startswith(b'T\x00') else 'utf-8'
            marker='Binary:\n'.encode(encoding);where=header_bytes.find(marker)
            if where<0:return None
            header=header_bytes[:where].decode(encoding)
            flags=re.search(r'^Flags:\s*(.*)$',header,re.M)[1].split()
            if 'real' not in flags or 'FastAccess' in flags:return None
            count=int(re.search(r'No\. Variables:\s*(\d+)',header)[1])
            if not 2<=count<=100000:return None
            stride=8+(count-1)*(8 if 'double' in flags else 4)
            offset=where+len(marker);size=stream.seek(0,2)
            points=(size-offset)//stride
            if points<=0:return None
            stream.seek(offset+(points-1)*stride)
            value=abs(struct.unpack('<d',stream.read(8))[0])
            return value if math.isfinite(value) else None
    except (OSError,ValueError,TypeError,IndexError,AttributeError,struct.error):
        return None


def _run(executable,folder,timeout,cancelled,*,progress=None,simulation_end=None):
    from calculation_scheduler import CalculationCancelled
    if cancelled():
        raise CalculationCancelled()
    folder=Path(folder).resolve()
    kwargs=dict(cwd=str(folder),stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        kwargs.update(startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    process=subprocess.Popen([executable,'-b',str(folder/'Flyback.cir')],**kwargs)
    start=time.monotonic()
    next_update=start
    try:
        while process.poll() is None:
            if cancelled():raise CalculationCancelled()
            now=time.monotonic()
            if progress and now>=next_update:
                elapsed=now-start;next_update=now+1.
                reached=partial_transient_time(folder/'Flyback.raw')
                message=f'本阶段 {elapsed:.0f} s / 超时上限 {timeout:g} s'
                if reached is not None:
                    message+=f' · 已推进 {reached*1000:.3g} ms'
                    if simulation_end and reached>0 and elapsed>5:
                        remaining=max(0.,elapsed*(simulation_end/reached-1))
                        message+=f' / {simulation_end*1000:g} ms，按当前速度尚需约 {remaining:.0f} s'
                progress(message)
            if time.monotonic()-start>timeout:
                reached=partial_transient_time(folder/'Flyback.raw')
                detail=f'；瞬态约推进至 {reached*1000:.4g} ms' if reached is not None else ''
                raise TimeoutError(f'LTspice 超过 {timeout:g} s{detail}；本工况未完成')
            time.sleep(.1)
        if process.returncode:raise RuntimeError(f'LTspice 返回退出码 {process.returncode}')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    return time.monotonic()-start


def _comparison_rows(case,measured,meta,periodicity=None,steady=None):
    result=case['result'];op=result['op'];rows=[]
    noniso=meta.get('topology') in ('BUCK','BOOST')
    tolerance=meta['settings']['comparison_tolerance_pct']
    stable=True
    for i in range(1,len(meta['hardware']['windings'])+1):
        a=measured.get(f'out{i}_earlier');b=measured.get(f'out{i}_before')
        if a is None or b is None or abs(a-b)>max(abs(b)*.01,.01):stable=False
    ready=stable and measured.get('fault_max',1)<.5 and (periodicity is None or periodicity['stable']) and (steady is None or steady['passed'])
    def add(name,unit,design,sim,scope='同名工况与量纲',comparable=True):
        delta=(sim-design)/abs(design)*100 if ready and comparable and design not in (None,0) and sim is not None else None
        status=('测量缺失' if sim is None else periodicity['reason']+' 仅统计' if periodicity and not periodicity['stable'] else '未稳态或处于保护' if not ready else '口径不同 仅并列' if not comparable
            else '不计算零基准百分比' if delta is None else '偏差待复核' if abs(delta)>tolerance else '偏差在提示阈值内')
        rows.append(dict(metric=name,unit=unit,design=design,simulation=sim,delta_percent=delta,status=status,scope=scope))
    add('输入电压','V',case['voltage'],measured.get('input_voltage'))
    add('实际开关频率','Hz',op['f_sw'] if meta.get('topology')=='QR-FLYBACK' else case['p']['f_sw'],measured.get('frequency_actual'),'稳态门极边沿周期测量')
    add('门极导通占空比','',op['D'],measured.get('duty_avg'))
    add('原边电流 RMS','A',op.get('I_p_rms',op['I_sw_rms']),measured.get('primary_rms'))
    add('原边电流峰值','A',op.get('I_p_pk',op['I_sw_pk']),measured.get('primary_peak'))
    add('原边电流平均值','A',op.get('I_p_avg',op['I_sw_avg']),measured.get('primary_avg'),
        '同一原边绕组全周期有符号均值' if 'I_p_avg' in op else '计算开关平均电流与物理原边绕组电流，含钳位换流差异')
    add('Vcs 峰值','V',op['I_sw_pk']*case['p']['Rs'],measured.get('vcs_peak'),'采样端含开通过渡尖峰',False)
    if noniso:
        for key,field,title in [('switch_rms','I_sw_rms','RMS'),('switch_avg','I_sw_avg','平均值'),('switch_peak','I_sw_pk','峰值')]:
            add('MOS Q1 电流 '+title,'A',op[field],measured.get(key),'实际串联 Rs 支路全周期电流',not meta['settings']['niso_edge_model'])
    elif meta.get('topology')=='QR-FLYBACK' and measured.get('switch_rms') is not None:
        for key,field,title in [('switch_rms','I_sw_rms','RMS'),('switch_avg','I_sw_avg','平均值'),('switch_peak','I_sw_pk','峰值')]:
            add('MOS Q1 沟道电流 '+title,'A',op[field],measured.get(key),
                '计算为传能电流包络；仿真为D→S沟道全带宽电流，含Coss放电与有限开关沿。RMS差异保留，峰值口径不同',key!='switch_peak')
    add('MOS Vds 峰值','V',op['V_sw_max'],measured.get('vds_peak'),'计算器钳位包络与瞬态寄生模型不同',False)
    outputs=result.get('outputs') or []
    for i,winding in enumerate(meta['hardware']['windings'],1):
        child=outputs[i-1]['op'] if outputs else op
        add(f'OUT{i} 输出平均电压','V',child['V_out'],measured.get(f'out{i}_before'),'设计模型稳态电压与含器件压降的 SPICE 输出')
        add(f'OUT{i} 电容端／反馈前电压','V',child.get('V_out_cap',child['V_out']),measured.get(f'out{i}_cap_before'),
            '防反管前电容端；只有所选一路进入反馈')
        add(f'OUT{i} 副边电流 RMS','A',child.get('I_s_rms',child['I_d_rms']),measured.get(f'out{i}_winding_rms'))
        add(f'OUT{i} 副边电流峰值','A',child.get('I_s_pk',child['I_d_pk']),measured.get(f'out{i}_winding_peak'))
        add(f'OUT{i} 副边电流平均值','A',child['I_d_avg'],measured.get(f'out{i}_winding_avg'))
        if meta.get('topology')=='QR-FLYBACK' and measured.get(f'out{i}_rectifier_rms') is not None:
            for key,field,title in [('rms','I_d_rms','RMS'),('avg','I_d_avg','平均值'),('peak','I_d_pk','峰值')]:
                add(f'OUT{i} 整流管电流 '+title,'A',child[field],measured.get(f'out{i}_rectifier_{key}'),
                    '整流管Dmain导通支路；并联Cj位移电流单列，绕组电流不替代整流导通电流')
        ripple=outputs[i-1]['ripple_pp'] if outputs else result['wf']['ripple_pp']
        add(f'OUT{i} 输出电容纹波峰峰值','V',ripple,measured.get(f'out{i}_pre_ripple'),'ESL/器件开关边沿及整流模型不同',False)
        add(f'OUT{i} 整流管反压','V',child['V_d_max'],measured.get(f'out{i}_diode_reverse'),'理想稳态反压与瞬态极值不同',False)
    if noniso:
        for row in rows:
            name=row['metric']
            if name.startswith('原边电流'):
                field={'原边电流 RMS':'I_L_rms','原边电流峰值':'I_L_pk','原边电流平均值':'I_L_avg'}[name]
                row['design']=op[field]
                row['delta_percent']=(row['simulation']-op[field])/abs(op[field])*100 if ready and op[field] and row['simulation'] is not None else None
                row['metric']=name.replace('原边电流','电感 L1 电流');row['scope']='同一电感 L1 的全周期电流'
                if row['delta_percent'] is not None:row['status']='偏差待复核' if abs(row['delta_percent'])>tolerance else '偏差在提示阈值内'
            row['metric']=row['metric'].replace('副边电流','二极管 D1 电流').replace('整流管反压','续流管反压' if meta['topology']=='BUCK' else '整流管反压')
    return rows,ready


def _startup_waveform(raw, output_count, end_s, return_node='v(sgnd)'):
    outputs={f'v(out{i})':(f'v(out{i})',return_node) for i in range(1,output_count+1)}
    optional=('v(input)','v(en)','v(ss)','v(ref)','v(fault)','v(comp)','v(vcc)','v(zcd)',
              'v(xu_ctrl:filtered)','v(xu_ctrl:trip)')
    signals={**outputs, **{name:(name,None) for name in optional if name in raw.names}}
    return raw.plot_samples(signals,float(raw.time[0]),end_s,bins=350)


def startup_excitation(raw, end_s, controller, startup_evidence):
    """Capture actual gated primary current near the startup winding peak."""
    from qr_spice_analysis import excitation_ramps
    names = ('v(gate)','v(sense)','v(drain)','i(lp)')
    if not all(name in raw.names for name in names) or end_s <= raw.time[0]:
        return dict(available=False,reason='缺少启动原边或门极的短窗口数据。')
    anchor = next((r['time_s'] for r in startup_evidence.get('rows', ())
                   if r['ref']=='LP' and r['channel']=='current' and r['time_s'] is not None),None)
    if anchor is None:
        trace=raw.trace('i(lp)')
        limit=int(np.searchsorted(raw.time,end_s,side='right'))
        peak=0.
        for start in range(0,limit,200000):
            samples=trace[start:min(limit,start+200000)]
            index=int(np.argmax(samples))
            if samples[index]>peak:
                peak=float(samples[index])
                anchor=float(raw.time[start+index])
    if anchor is None:
        return dict(available=False,reason='启动窗口没有可定位的正向原边电流。')
    half_width=max(2.5/float(controller['FSW']),60e-6)
    observed = raw.samples(names,max(float(raw.time[0]),anchor-half_width),min(end_s,anchor+half_width),None)
    return excitation_ramps(observed,controller)


def _simulate_nominal(executable,folder,case,meta,settings,record,cancelled,progress=None):
    from calculation_scheduler import CalculationCancelled
    from spice_analysis import cycle_quality,statistics
    qr=meta.get('topology')=='QR-FLYBACK'
    forward=meta.get('topology')=='ACF-FORWARD'
    noniso=meta.get('topology') in ('BUCK','BOOST')
    fault_case=record['fault_test']
    if qr:
        from qr_spice_analysis import cycle_quality
    started=time.monotonic()
    raw=None
    try:
        record['elapsed_s']=_run(executable,folder,settings['simulation_timeout_s'],cancelled,
            progress=progress,simulation_end=settings['stop_ms']*1e-3)
        measured,log,errors,warnings=read_log(folder/'Flyback.log')
        raw=TransientRaw(folder/'Flyback.raw')
        if noniso:
            raw.names['i(lp)']=raw.names['i(l1)']
            raw.names['i(ls1)']=raw.names['i(v_d1)']
        if not fault_case:
            requested_end=settings['step_ms']*1e-3
            start_end=min(float(raw.time[-1]),requested_end)
            record['startup_window_end_s']=start_end
            record['startup_window']=_startup_waveform(raw,len(meta['hardware']['windings']),start_end)
            if meta.get('white_box_probes'):
                from spice_white_box import collect_startup
                record['white_box_startup']=collect_startup(raw,meta['white_box_probes'],0.,requested_end)
            if meta.get('topology') in ('QR-FLYBACK','FLYBACK'):
                record['startup_excitation']=startup_excitation(raw,start_end,meta['resolved_controller'],
                    record.get('white_box_startup') or {})
        if errors or not math.isclose(raw.time[-1],settings['stop_ms']*1e-3,abs_tol=1e-10):
            raise ValueError('仿真未到结束时刻或日志存在求解失败：'+'; '.join(errors))
        if qr:
            from qr_spice_analysis import startup_gate_current
            record['qr_calculation_model']=case['result']['op'].get('qr_multi_model') or {}
            record['qr_startup']=startup_gate_current(raw,settings['step_ms']*1e-3,meta['resolved_controller']['VG'],
                output_count=len(meta['hardware']['windings']),feedback_output=int(meta.get('feedback_output',1)))
        required=['primary_rms','primary_peak','vds_peak','fault_max','input_voltage','frequency_actual','duty_avg']+[f'out{i}_before' for i in range(1,len(meta['hardware']['windings'])+1)]
        missing = [k for k in required if k not in measured]
        if missing:
            from spice_analysis import protection_stop
            record.update(measurements=measured,warnings=warnings,missing_measurements=missing,
                          actual_end_s=float(raw.time[-1]),points=len(raw.time),nominal_comparable=False)
            trip = protection_stop(raw, measured, meta['resolved_controller']['FSW'])
            if trip:
                record['protection_stop'] = trip
                names = [f'v(out{i})' for i in range(1,len(meta['hardware']['windings'])+1)]
                record['startup'] = raw.samples(names+['v(ss)','v(fault)'],0,float(raw.time[-1]),3000)
                raise ValueError(f"保护在 {trip['first_trip_s']*1e3:.4g} ms 动作（{trip['cause']}）；"
                                 f"测量窗占空比 {measured.get('duty_avg',float('nan')):.3g}，缺少 "+'、'.join(missing))
            raise ValueError('未取得必要的测量：'+'、'.join(missing))
        record.update(complete=True,measurements=measured,warnings=warnings,
            actual_end_s=float(raw.time[-1]),points=len(raw.time))
        frequency=meta['resolved_controller']['FSW']
        record['periodicity']=cycle_quality(raw,frequency,settings['step_ms']*1e-3-400/frequency,
            settings['step_ms']*1e-3-10/frequency,meta['resolved_controller']['VG'],tolerance_pct=settings['cycle_tolerance_pct'])
        if forward:
            from acf_spice import timing_quality
            record['acf_timing']=timing_quality(raw,frequency,settings['step_ms']*1e-3-10/frequency,
                meta['resolved_controller']['VG'],meta['hardware']['R_dc_p'])
            if not record['acf_timing']['passed']:
                record['periodicity'].update(stable=False,reason='有源钳位死区／磁复位检查未通过')
        if qr and record['periodicity'].get('frequency_mean_hz'):
            measured['frequency_actual']=record['periodicity']['frequency_mean_hz']
            meta['qr_measured_min_frequency_hz']=record['periodicity']['frequency_min_hz']
            from qr_spice_analysis import cycle_current_statistics
            audit=cycle_current_statistics(raw,record['periodicity'],len(meta['hardware']['windings']),
                current_observation=meta.get('current_observation'))
            record['qr_current_audit']=audit
            if audit['available']:
                audit['original_meas']={key:measured.get(key) for key in audit['measurements']}
                measured.update(audit['measurements'])
        if forward or noniso or qr:
            from spice_analysis import steady_quality
            record['steady_before_step']=steady_quality(raw,frequency,settings['step_ms']*1e-3,len(meta['hardware']['windings']))
        if qr and (record.get('qr_current_audit') or {}).get('available'):
            from qr_spice_analysis import charge_balance
            balance=charge_balance(record['qr_current_audit'],case)
            record['qr_charge_balance']=balance
            record['steady_before_step']['passed'] &= balance['passed']
            record['steady_before_step']['reason'] += '；'+balance['reason']
        elif qr:
            record['steady_before_step']['passed']=False
            record['steady_before_step']['reason']+='；未取得连续完整周期的电流证据'
        record['rows'],record['nominal_comparable']=_comparison_rows(case,measured,meta,record['periodicity'],record.get('steady_before_step'))
        if not fault_case:
            from spice_black_box import full_load_ports
            record['black_box']=full_load_ports(raw,case,end_s=settings['step_ms']*1e-3,
                frequency_hz=frequency,return_node='v(sgnd)',comparable=record['nominal_comparable'])
        if fault_case:
            for row in record['rows']:row.update(delta_percent=None,status='短路测试 不与标称判差')
        names=['v(out'+str(i)+')' for i in range(1,len(meta['hardware']['windings'])+1)]
        record['startup']=raw.samples(names+['v(ss)','v(fault)'],0,float(raw.time[-1]),3000)
        end=settings['step_ms']*1e-3-10/frequency;begin=end-5/frequency
        cycles=record['periodicity']['cycles']
        if qr and cycles:
            visible_cycles=cycles[-5:]
            begin=visible_cycles[0]['start_s']
            end=visible_cycles[-1]['end_s']
        if not fault_case and meta.get('white_box_probes'):
            from spice_white_box import collect
            audit_start=(record.get('qr_current_audit') or {}).get('start_s',settings['step_ms']*1e-3-200/frequency)
            record['white_box']=collect(raw,meta['white_box_probes'],audit_start,end,begin,
                comparable=record['nominal_comparable'],tolerance=settings['comparison_tolerance_pct'])
        record['switching']=raw.samples(['v(drain)','v(sense)','v(gate)','v(comp)','v(ramp)','i(lp)']+(['v(zcd)'] if qr else [])+
            (['v(sync)','v(auxgate)','v(aclamp)','v(vin_bus)','i(c_active)']+[f'i(lo{i})' for i in range(1,len(meta['hardware']['windings'])+1)] if forward else [])+
            ['i(ls'+str(i)+')' for i in range(1,len(meta['hardware']['windings'])+1)]+
            [f'v({node}{i})' for i in range(1,len(meta['hardware']['windings'])+1) for node in ('out','cap')],begin,end,None if qr else 2400)
        if forward:
            for i in range(1,len(meta['hardware']['windings'])+1):
                key=f'i(ls{i})'
                record['switching'][key]=(-np.asarray(record['switching'][key])).tolist()
        wf=case['result']['wf'];sample_time=np.asarray(record['switching']['time'])
        if qr or math.isclose(case['p']['f_sw'],meta['resolved_controller']['FSW']):
            design_frequency=case['result']['op']['f_sw'] if qr else case['p']['f_sw']
            origin=begin if qr and cycles else next(
                (row['gate_rise_s'] for row in cycles if row.get('gate_rise_s') is not None),0.)
            record['design_phase_origin_s']=origin
            phase=np.mod(sample_time-origin,1/design_frequency)
            # LP is a physical winding current, not magnetising current.
            record['design_switching']={key:np.interp(phase,wf['t'],wf[source]).tolist()
                for key,source in [('i_p','iL' if noniso else 'i_primary' if 'i_primary' in wf else 'i_p' if forward else 'i_sw'),('v_sw','v_sw')]}
        record['branches']=[]
        for i in range(1,len(meta['hardware']['windings'])+1):
            child=wf['outputs'][i-1] if wf.get('outputs') else wf
            branch=dict(id=i,name=(case['result']['outputs'][i-1]['name'] if case['result'].get('outputs') else 'OUT1'),
                simulation_ripple=statistics(raw.time,raw.trace(f'v(out{i})'),settings['step_ms']*1e-3-200/frequency,settings['step_ms']*1e-3-10/frequency))
            if qr or math.isclose(case['p']['f_sw'],frequency):
                branch['design_current']=np.interp(phase,child['t'],child['i_s']).tolist()
                branch['design_ripple']=np.interp(phase,child['t'],child['vout_ripple']).tolist()
                branch['design_ripple_pp']=float(child['ripple_pp'])
                if forward:
                    branch['design_choke']=np.interp(phase,child['t'],child['iL']).tolist()
                    child_op=case['result']['outputs'][i-1]['op'] if case['result'].get('outputs') else case['result']['op']
                    branch.update(choke_design_rms=child_op['I_L_rms'],choke_design_peak=child_op['I_L_pk'],choke_design_valley=child_op['I_L_min'])
            record['branches'].append(branch)
        fault=raw.trace('v(fault)');indices=np.flatnonzero(np.diff((fault>.5).astype(np.int8))>0)
        record['fault_events_s']=raw.time[indices+1].tolist()[:100]
        record['source_model_hash']=meta['library_sha256']
    except CalculationCancelled:raise
    except Exception as exc:record.update(complete=False,error=str(exc))
    finally:
        record['wall_elapsed_s']=time.monotonic()-started
        if raw is not None:raw.close()


def compare_design(run,destination,*,cancelled=lambda:False,progress=None,executable=None,parallel=True):
    """Publish the report formats from the same frozen simulation evidence."""
    from spice_export import project_files,normalize_settings
    from calculation_scheduler import CalculationCancelled
    executable=executable or find_ltspice()
    if not executable:raise ValueError('未检测到 LTspice。请在桌面仿真设置中选择 LTspice.exe 后重试')
    bundle=run.runtime_bundle();p=bundle['base_spec']
    if p.get('topology') == 'LLC':
        from llc_spice_comparison import compare_design as compare_llc
        return compare_llc(bundle,destination,executable=executable,cancelled=cancelled,
                           progress=progress,parallel=parallel)
    from cot_settings import active as cot_active
    if cot_active(p):
        from cot_spice_comparison import compare_design as compare_cot
        return compare_cot(bundle,destination,executable=executable,cancelled=cancelled,progress=progress,parallel=parallel)
    settings=normalize_settings(p.get('spice_config'))
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    report_path=destination if destination.suffix.lower()=='.docx' else destination.with_suffix('.docx')
    xlsx_path=destination if destination.suffix.lower()=='.xlsx' else destination.with_suffix('.xlsx')
    zip_path=destination if destination.suffix.lower()=='.zip' else destination.with_suffix('.zip')
    from spice_export import MODEL_VERSION
    qr=p.get('topology')=='QR-FLYBACK'
    if qr:
        from qr_spice_export import MODEL_VERSION
    forward=p.get('topology')=='ACF-FORWARD'
    noniso=p.get('topology') in ('BUCK','BOOST')
    if noniso:
        from nonisolated_spice import MODEL_VERSION
    if forward:
        from acf_spice import MODEL_VERSION
    from spice_studies import run_fra,run_cross,collect_study
    from spice_boundary import endpoint_cases, run_load_transient
    from spice_analysis import cycle_quality,statistics,steady_quality
    from spice_planning import execution_plan
    from spice_result_cache import NominalCache,cache_key
    if qr:
        from qr_spice_analysis import cycle_quality
    plan=execution_plan(p,settings)
    evidence=dict(schema='powerdesign-spice-comparison-2',model=MODEL_VERSION,cases=[],settings=settings,topology=p.get('topology'),plan=plan,
                  input_range_V=[p.get('V_in_min',p.get('V_in')),p.get('V_in_max',p.get('V_in'))])
    from engineering_acceptance import input_fingerprint
    evidence['input_fingerprint'] = input_fingerprint(p)
    started=time.monotonic();cache=NominalCache()
    processors=(_simulate_nominal,_comparison_rows,cycle_quality,statistics,steady_quality,TransientRaw.samples,TransientRaw.__init__)
    cases=endpoint_cases(p,bundle['cases'])
    bundle=dict(bundle,cases=cases)
    total=len(plan['stages'])
    per_endpoint = (total - int(bool(settings['line_load_enabled']))) // len(cases)
    workers = endpoint_workers(len(cases), settings['simulation_threads'], parallel=parallel)
    evidence['execution'] = dict(endpoint_workers=workers, threads_per_case=int(settings['simulation_threads']))
    cache_io = Lock()
    with tempfile.TemporaryDirectory(prefix='spice-compare-',dir=destination.parent) as temporary:
        work = Path(temporary)

        def execute_study(folder, timeout, stopped, update):
            analysis = (folder/'analysis.inc').read_text(encoding='ascii')
            stop_match = re.search(r'(?im)^\.tran\s+\S+\s+([\d.eE+-]+)\s', analysis)
            return _run(executable, folder, timeout, stopped, progress=update,
                        simulation_end=float(stop_match[1]) if stop_match else None)

        def solve(case, cancelled, notify):
            archive_files = {}
            records = []
            line_load_inputs = None
            done = 0
            for fault_case in ([False,True] if settings['short_test'] else [False]):
                if cancelled():raise CalculationCancelled()
                done+=1;label=case['id']+('_短路测试' if fault_case else '_标称负载')
                notify(done, 'LTspice '+label)
                q=copy.deepcopy(p);q['spice_config']=dict(settings,short_test=int(fault_case),load_after=1.)
                files=project_files(q,bundle=bundle)
                meta=json.loads(files['manifest.json'])
                if not fault_case:
                    from spice_white_box import prepare
                    meta['white_box_probes']=prepare(files,case)
                folder=work/label;folder.mkdir()
                for name,data in files.items():
                    if name=='design_params.inc':
                        data=('\n'.join(line for line in data.decode('ascii').splitlines() if not line.startswith(('.step ','.param VIN=')))+f'\n.param VIN={case["voltage"]:.12g}\n').encode('ascii')
                        files[name]=data
                    (folder/name).write_bytes(data)
                    archive_files[label+'/'+name]=data
                record=dict(id=label,voltage=case['voltage'],fault_test=fault_case,complete=False,measurements={},rows=[],plots=[],
                    controller=meta['resolved_controller'],slope=meta['slope'],feedback_output=meta['feedback_output'],
                    qr=meta.get('qr'),acf=meta.get('acf'),approximation_notes=meta.get('approximation_notes',[]),
                    niso=meta.get('niso'),
                    hardware=meta['hardware'],source_hashes={k:hashlib.sha256(v).hexdigest() for k,v in files.items() if k.endswith(('.cir','.inc','.lib'))},
                    loop=dict(available=False,error='未启用 FRA'),cross=dict(supported=False,error='未启用交叉调整率扫描'))
                records.append(record)
                if case['result']['op'].get('acf_model'):
                    cm=case['result']['op']['acf_model']
                    record['calculation_model']={key:cm[key] for key in ('kind','revision','assumptions','mesh','current_mesh_verified','normalized_residual','energy_balance_relative')}
                key=None;cached=None
                if settings['simulation_reuse'] and not fault_case:
                    try:
                        key=cache_key(files,case,settings,executable,processors)
                        with cache_io:
                            cached=cache.load(key)
                    except (ValueError,TypeError,OSError):pass
                if cached is not None:
                    cached_record,log,created_at=cached
                    record.update(cached_record,id=label)
                    record['cache']=dict(hit=True,created_at=created_at,key=key)
                    record['wall_elapsed_s']=0.
                    archive_files[label+'/Flyback.log']=log
                    notify(done,label+' · 复用已通过的标称仿真 '+created_at)
                else:
                    _simulate_nominal(executable,folder,case,meta,settings,record,cancelled,
                        progress=(lambda text:notify(done,label+' · '+text)) if progress else None)
                    record['cache']=dict(hit=False)
                    if record.get('complete') and record.get('nominal_comparable') and not fault_case:
                        from flyback_cap_boundary import attach_comparison
                        attach_comparison(case['p'],case['result']['op'],record,cancelled)
                    if (folder/'Flyback.log').is_file():
                        log=(folder/'Flyback.log').read_bytes()
                        archive_files[label+'/Flyback.log']=log
                        if key:
                            with cache_io:
                                if not cancelled():
                                    cache.store(key,record,log)
                if fault_case:continue
                if settings['line_load_enabled'] and case is cases[-1]:
                    line_load_inputs = files, meta
                phase=case['id']+' 环路 FRA'
                def phase_progress(message):
                    nonlocal phase
                    phase=case['id']+' '+message
                    notify(done,phase)
                def execute(study_folder,timeout):
                    return execute_study(study_folder,timeout,cancelled,
                        (lambda text:notify(done,phase+' · '+text)) if progress else None)
                done+=1
                phase_progress('反馈路 10% ↔ 90% 双向负载阶跃')
                if record.get('complete') and not record.get('protection_stop'):
                    study=work/(case['id']+'_双向阶跃')
                    record['load_transient']=run_load_transient(files,case,settings,study,execute,
                        frequency_hz=record.get('measurements',{}).get('frequency_actual') or meta['resolved_controller']['FSW'])
                    if study.is_dir():archive_files.update(collect_study(study,study.name))
                else:
                    record['load_transient']=dict(available=False,complete=False,error='满载仿真未完成或触发保护，双向阶跃未运行')
                if settings['fra_enabled']:
                    done+=1
                    phase_progress('原生 FRA')
                    if record['complete'] and record['periodicity']['stable'] and record['nominal_comparable']:
                        study=work/(case['id']+'_FRA')
                        operating_point=None
                        if qr:
                            from spice_studies import qr_measured_point
                            # Restore the measured frequency boundary for a
                            # reused QR record as well as a fresh RAW result.
                            meta['qr_measured_min_frequency_hz']=record['periodicity']['frequency_min_hz']
                            operating_point=qr_measured_point(case,record)
                        record['loop']=run_fra(files,case,meta,settings,study,execute,
                            progress=phase_progress,
                            operating_point=operating_point)
                        if study.is_dir():archive_files.update(collect_study(study,study.name))
                        if (study/'half_amplitude').is_dir():archive_files.update(collect_study(study/'half_amplitude',study.name+'/half_amplitude'))
                    else:record['loop']['error']='标称工况未通过逐周期与直流稳态检查，不提供有效线性化 FRA'
                if plan['cross_enabled']:
                    done+=1
                    phase_progress('交叉调整率角点')
                    study=work/(case['id']+'_交叉调整率')
                    if not record.get('nominal_comparable'):
                        record['cross']=dict(supported=True,complete=False,records=[],summary=[],
                            error='标称工况未完成或未通过稳态／逐周期检查，暂停负载角点扫描；请先调整观察时间或控制器。')
                    else:
                        record['cross']=run_cross(files,case,meta,settings,study,execute,cancelled=cancelled,
                            progress=phase_progress)
                    if study.is_dir():archive_files.update(collect_study(study,study.name))
                    for retry in study.glob('retry_*'):
                        if retry.is_dir():archive_files.update(collect_study(retry,study.name+'/'+retry.name))
            return records, archive_files, line_load_inputs

        boundaries = run_endpoint_cases(cases, solve, workers=workers, cancelled=cancelled,
                                        progress=progress, stages_per_case=per_endpoint, total=total)
        archive_files = {}
        for records, captured, _ in boundaries:
            evidence['cases'].extend(records)
            archive_files.update(captured)
        if settings['line_load_enabled']:
            baselines = [item for item in evidence['cases'] if not item['fault_test']]
            if all(item.get('nominal_comparable') for item in baselines):
                from isolated_outputs import output_specs
                from spice_line_load import run_line_load
                label = '黑盒动态稳定度：线载联合跳变'
                if progress:
                    progress(total, total, label)
                def execute_line(folder, timeout):
                    return execute_study(folder,timeout,cancelled,
                        (lambda text:progress(total,total,label+' · '+text)) if progress else None)
                files, meta = boundaries[-1][2]
                study = work/'line_load'
                evidence['line_load_stability'] = run_line_load(files, output_specs(p) or [p], [item['voltage'] for item in cases],
                    settings, meta['resolved_controller']['FSW'], study, execute_line)
                if study.is_dir():archive_files.update(collect_study(study, study.name))
            else:
                evidence['line_load_stability'] = dict(complete=False,error='边界满载基线未稳态，未启动线载联合试验')
        if cancelled():raise CalculationCancelled()
        from spice_comparison_report import write_report
        from spice_comparison_xlsx import write_spice_xlsx
        pending_report=work/'comparison.docx'
        pending_xlsx=work/'comparison.xlsx'
        evidence['simulation_wall_s']=time.monotonic()-started
        archive_files['comparison.json']=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
        try:
            write_report(pending_report,evidence)
            write_spice_xlsx(pending_xlsx,evidence)
        except Exception as exc:
            recovery=destination.with_name(destination.stem+f'-evidence-{time.time_ns()}.zip')
            with zipfile.ZipFile(recovery,'w',zipfile.ZIP_DEFLATED) as archive:
                for name,data in archive_files.items():archive.writestr(name,data)
            raise RuntimeError('报告排版未完成，实际仿真证据已保留：'+str(recovery)) from exc
        archive_files[report_path.name]=pending_report.read_bytes()
        archive_files[xlsx_path.name]=pending_xlsx.read_bytes()
        pending_zip=work/'comparison.zip'
        with zipfile.ZipFile(pending_zip,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in archive_files.items():archive.writestr(name,data)
        if cancelled():raise CalculationCancelled()
        os.replace(pending_xlsx,xlsx_path)
        os.replace(pending_report,report_path)
        os.replace(pending_zip,zip_path)
    nominal=[c for c in evidence['cases'] if not c['fault_test']]
    fra_success=sum(c['loop'].get('available',False) for c in nominal)
    cross_cases=[c for c in nominal if c['cross'].get('supported')]
    cross_success=sum(c['cross'].get('complete',False) for c in cross_cases)
    cross_simulation_success=sum(c['cross'].get('simulation_complete',c['cross'].get('complete',False)) for c in cross_cases)
    cross_design_success=sum(c['cross'].get('design_complete',c['cross'].get('complete',False)) for c in cross_cases)
    return dict(path=str(zip_path),report_path=str(report_path),xlsx_path=str(xlsx_path),
        successful=sum(c['complete'] for c in evidence['cases']),
        total=len(evidence['cases']),fra_successful=fra_success,fra_total=len(nominal) if settings['fra_enabled'] else 0,
        cross_successful=cross_success,cross_total=len(cross_cases),
        cross_simulation_successful=cross_simulation_success,cross_design_successful=cross_design_success,
        cached_nominal=sum(c.get('cache',{}).get('hit',False) for c in nominal),
        elapsed_s=time.monotonic()-started,
        incomplete=bool(settings['line_load_enabled'] and not evidence.get('line_load_stability',{}).get('complete')) or any(not c['complete'] for c in evidence['cases']) or any(not c.get('nominal_comparable',False) or
            not c.get('load_transient',{}).get('complete') for c in nominal) or
            bool(settings['fra_enabled'] and fra_success<len(nominal)) or
            bool(settings['cross_enabled'] and cross_success<len(cross_cases)))
