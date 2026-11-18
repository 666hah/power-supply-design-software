"""Owned, cancellable LTspice system transient with persistent failure evidence."""
from __future__ import annotations
from datetime import datetime
import copy
import hashlib
import json
from pathlib import Path
import time
import uuid


def _json(path,value):
    tmp=path.with_suffix('.writing');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');tmp.replace(path)


def run(project_snapshot,folder,*,ltspice=None,cancelled=lambda:False,progress=None):
    from calculation_scheduler import CalculationCancelled
    from system_sequence_export import export_project
    from system_sequence_analysis import analyze
    from system_sequence_report import write
    from spice_runtime import find_ltspice,_run,read_log
    project_snapshot=copy.deepcopy(project_snapshot)
    root=Path(folder)/('联合启停-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);start=time.monotonic();manifest={}
    result=dict(status='failed',summary=dict(sources=[],units=[],loads=[]),waveforms=dict(time=[]),events=[],failure_reasons=[],limitations=[])
    result_path=root/'result.json';report={}
    def tell(message):
        with (root/'progress.log').open('a',encoding='utf8') as f:f.write(datetime.now().isoformat(timespec='seconds')+' '+str(message)+'\n')
        if progress:
            try:progress(message)
            except Exception:
                # A failed UI observer cannot orphan a solver or prevent its
                # evidence receipt from being written.
                pass
    try:
        tell('冻结电源树输入，准备各单元实际开关级电路。')
        manifest=export_project(project_snapshot,root,cancelled=cancelled,progress=tell)
        if cancelled():raise CalculationCancelled()
        executable=ltspice or find_ltspice()
        if not executable or not Path(executable).is_file():raise ValueError('未找到LTspice，请在联合启停窗口选择实际可执行程序。')
        tell('开始整张电源树的联合瞬态；仅本任务拥有的LTspice进程可被取消。')
        elapsed=_run(str(Path(executable).resolve()),root,manifest['settings']['timeout_s'],cancelled,progress=tell,simulation_end=manifest['settings']['stop_s'])
        if cancelled():raise CalculationCancelled()
        log=root/'Flyback.log'
        if not log.is_file():raise RuntimeError('LTspice未生成日志，保留电路供复核。')
        _,log_text,errors,warnings=read_log(log)
        if errors:raise RuntimeError('LTspice日志报告错误：'+'；'.join(errors))
        result=analyze(root/'Flyback.raw',manifest)
        result.update(simulator=str(Path(executable).resolve()),simulation_elapsed_s=elapsed,log_warnings=warnings)
        if result['status']!='completed':tell('RAW或必要探针检查未完成，报告仅保留诊断，不给出通过结论。')
        else:tell('瞬态完成；正在统计完整RAW的浪涌、时序、采样与保护事件。')
    except CalculationCancelled:
        result.update(status='cancelled',failure_reasons=['用户取消，本次未完成；已有文件仅供诊断。'])
        tell('已终止本任务仿真；没有把部分波形当作完成结果。')
    except Exception as exc:
        result.update(status='failed',failure_reasons=[str(exc)])
        tell('未完成：'+str(exc))
    if result['status']!='completed' and (root/'Flyback.log').is_file():
        try:
            _,_,errors,warnings=read_log(root/'Flyback.log')
            result['failure_reasons']=list(dict.fromkeys(result['failure_reasons']+errors))
            result['log_warnings']=warnings
        except (OSError,ValueError):pass
    result.update(schema='power.system-sequence-result/1',calculation_and_simulation_elapsed_s=time.monotonic()-start,directory=str(root))
    result['evidence_files']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('Flyback.cir','SystemNetwork.inc','project.json','manifest.json','Flyback.log') if (root/name).is_file()}
    _json(result_path,result)
    report_start=time.monotonic()
    try:
        # Even failure/cancellation gets an explicit readable receipt. None of
        # the RAW values or unavailable conclusions are substituted by history.
        report=write(root,manifest,result)
    except Exception as exc:
        result['report_error']=str(exc);_json(result_path,result);tell('报告写入失败，JSON和日志已保留：'+str(exc))
    result.update(report_elapsed_s=time.monotonic()-report_start,total_elapsed_s=time.monotonic()-start)
    _json(result_path,result)
    tell('结果目录：'+str(root))
    return dict(status=result['status'],directory=str(root),result_path=str(result_path),summary=result.get('summary',{}),report_error=result.get('report_error'),**report)
