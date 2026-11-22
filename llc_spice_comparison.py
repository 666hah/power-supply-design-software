"""Run the LLC independent switch model and package traceable evidence."""

import math
from pathlib import Path
import tempfile
import time
import zipfile


def _cases(bundle):
    return bundle['cases'][:1] if bundle.get('same_voltage') else bundle['cases']


def export_files(p, bundle=None):
    from input_voltage_range import calculate_input_endpoints
    from llc_spice import project_files
    from spice_export import _json
    from app_resources import resource_path

    bundle = bundle or calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
    files, models = {}, []
    for case in _cases(bundle):
        if not case.get('result'):
            raise ValueError(f"{case['id']} 无法导出 LLC：{case.get('error','无周期解')}")
        folder = case['id']
        case_files = project_files(case['p'],case['result']['op'])
        files.update({folder+'/'+name:blob for name,blob in case_files.items()})
        models.append(dict(id=case['id'],voltage=case['voltage'],project=folder+'/LLC.asc'))
    notes = ['每个输入端点有自己的可运行 ASC 和 CIR。两端采用同一套磁件、器件和 PI 增益。']
    files['manifest.json'] = _json(dict(model_version='llc-switched-1',topology='LLC',cases=models,
                                       approximation_notes=notes)).encode('utf-8')
    files['README.md'] = ('# LLC 开关仿真\n\n'+'\n'.join(f"- {row['id']} {row['voltage']:g} V，打开 `{row['project']}`。"
                          for row in models)+'\n\n'+notes[0]+'\n').encode('utf-8')
    guide=resource_path('docs/LLC_DESIGN.md')
    if guide.is_file():
        files['LLC_DESIGN.md']=guide.read_bytes()
    return files


def _measurements(op, result, measured, parameters, settings):
    from llc_design import comparison_capacitors

    x = op['llc']
    rows = []
    def compare(name, unit, a, b, white=False):
        rows.append(dict(name=name,unit=unit,expected=a,observed=b,white=white,
                         error_pct=(b/a-1)*100 if a is not None and b is not None and abs(a)>1e-12 else None))
    for name,unit,a,b in (
        ('输出端口电压','V',op['V_out'],measured['V_out_V']),
        ('开关频率','kHz',op['f_sw']/1000,measured['frequency_Hz']/1000),
        ('输出功率','W',op['P_out'],measured['power_out_W']),
        ('输出纹波','mVpp',x['output_ripple_V']*1000,measured['ripple_Vpp']*1000),
        ('谐振电流有效值','A',op['I_L_rms'],measured['I_res_rms_A']),
        ('谐振电流峰值','A',op['I_L_pk'],measured['I_res_peak_A']),
        ('励磁电流有效值','A',x['im_rms_A'],measured['I_mag_rms_A']),
        ('整流汇流有效值','A',x['rectifier_rms_A'],measured['I_rect_rms_A']),
        ('整流汇流峰值','A',x['rectifier_peak_A'],measured['I_rect_peak_A']),
        ('谐振电容绝对峰压','V',x['cr_peak_V'],measured['V_cr_peak_V']),
    ):
        compare(name,unit,a,b,white=len(rows)>=4)
    for i,(v,rms,turnon) in enumerate(zip(measured['switch_Vds_peak_V'],measured['switch_I_rms_A'],
                                             measured['switch_Vds_pre_turnon_median_V']),1):
        compare(f'Q{i} 漏源峰压（计算列为母线平台）','V',op['V_in_bus'],v,True)
        rows[-1]['error_pct']=None
        compare(f'Q{i} 沟道电流有效值','A',op['I_sw_rms'],rms,True)
        compare(f'Q{i} 门极开通前残压','V',x['v_zvs'],turnon,True)
    for i,(v,rms) in enumerate(zip(measured['diode_Vr_peak_V'],measured['diode_I_rms_A']),1):
        compare(f'D{i} 反向峰压','V',op['V_d_max'],v,True)
        compare(f'D{i} 电流有效值','A',op['I_d_rms'],rms,True)
    matched_caps = comparison_capacitors(parameters,op,result['wf'],bool(settings['include_cap_esl']))
    for name, bank, measured_key in (('输入','input','input_bank_rms_A'),('输出','output','output_bank_rms_A')):
        cap = matched_caps[bank]['caps']
        for i,(one,value) in enumerate(zip(cap,measured[measured_key]),1):
            compare(f'{name}电容 {i} 纹波 RMS','A',one['total'],value,True)
    return rows


def _fra_grid(settings, fmax):
    lo, hi = settings['fra_start_hz'], min(settings['fra_stop_hz'],fmax)
    if hi <= lo:
        return []
    octaves = int(settings['fra_oct'])
    return sorted({round(lo*2**(k/octaves),6) for k in range(math.floor(math.log2(hi/lo)*octaves)+1)}
                  | {hi})


def compare_design(bundle, destination, *, executable, cancelled, progress, parallel=True):
    from calculation_scheduler import CalculationCancelled
    from llc_report import export_comparison
    from llc_comparison_xlsx import write_llc_comparison_xlsx
    from llc_spice import measure_raw, write_project
    from loop_tuning import analyze_loop
    from plants import build_loop_models
    from spice_export import _json, normalize_settings
    from spice_runtime import _run, endpoint_workers
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    from engineering_acceptance import input_fingerprint

    cases = _cases(bundle)
    settings = normalize_settings(bundle['base_spec'].get('spice_config'))
    boundaries = [(case,_fra_grid(settings,min(case['p']['llc_fmin']/5,
                          (case.get('result') or {}).get('op',{}).get('f_sw',case['p']['llc_fmin'])/12))
                   if settings['fra_enabled'] and case.get('result') else []) for case in cases]
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    report_file = destination.with_suffix('.docx')
    xlsx_file = destination.with_suffix('.xlsx')
    zip_file = destination.with_suffix('.zip')
    total = sum(2+2*len(freqs) for _,freqs in boundaries)
    progress_lock=Lock()
    done=0

    def status(label, advance=False):
        nonlocal done
        with progress_lock:
            if advance:
                done+=1
            if progress:
                progress(done,total,label)

    with tempfile.TemporaryDirectory(prefix='llc-spice-',dir=destination.parent) as directory:
        root=Path(directory)

        def one_stage(folder,p,op,label,**opts):
            status(label)
            project=write_project(folder,p,op,**opts)
            try:
                timeout = settings['fra_timeout_s'] if opts.get('fra_hz') else settings['simulation_timeout_s']
                _run(executable, folder, timeout, cancelled,
                     progress=lambda msg:status(label+' · '+msg),
                     simulation_end=project['manifest']['schedule']['stop_s'])
                return measure_raw(folder/'Flyback.raw',p,op,load_step=opts.get('load_step',False),fra_hz=opts.get('fra_hz'))
            finally:
                status(label,advance=True)

        def one_case(item):
            case,freqs=item
            label=f"{case['id']} {case['voltage']:g} V"
            row=dict(id=case['id'],voltage=case['voltage'],label=label,status='未完成',
                     dynamic_status='未执行',fra_status='未启用' if not settings['fra_enabled'] else '未执行')
            if not case.get('result'):
                row['error']=case.get('error','周期解失败')
                return row
            p, result=case['p'],case['result']
            op=result['op']
            base=root/case['id']
            row['notes']=list(op['llc']['notes'])
            try:
                row['measured']=steady=one_stage(base/'steady',p,op,label+' · 满载与启动')
                row['metrics']=_measurements(op,result,steady,p,settings)
                row['out_of_tolerance']=sum(
                    item['error_pct'] is not None and abs(item['error_pct'])>settings['comparison_tolerance_pct']
                    for item in row['metrics'])
                row['status']='完成' if steady['ready'] and steady['no_gate_overlap'] else '需复核'
                if row['status']!='完成':
                    row['error']='满载输出、周期收敛或保护检查需复核。'
            except CalculationCancelled:
                raise
            except Exception as error:
                row['error']=str(error)
                return row
            try:
                row['dynamic']=one_stage(base/'dynamic',p,op,label+' · 10%→90%→10%',load_step=True)
                dynamic=row['dynamic']
                verified=not dynamic['fault'] and all(step['pre_in_band'] and step['post_in_band']
                    and step['settle_2pct_s'] is not None for step in dynamic['load_steps'])
                row['dynamic_status']='完成' if verified else '开关保护或稳压需复核'
            except CalculationCancelled:
                raise
            except Exception as error:
                row['dynamic_status']='失败'
                row['notes'].append(f'阶跃失败：{error}')
            try:
                models,_=build_loop_models(p,op)
                row['loop']=analyze_loop(p,models,op)
            except (ValueError, RuntimeError) as error:
                row['notes'].append(f'计算环路未完成：{error}')
                models=None
            if not freqs or not models:
                return row
            row['fra']=[]
            peak_amplitude=p['V_out']*settings['fra_amplitude_pct']*.005
            for i,hz in enumerate(freqs,1):
                if cancelled():
                    raise CalculationCancelled()
                response=complex(models[2](2j*math.pi*hz))
                data=dict(frequency_Hz=hz,calc_db=20*math.log10(max(abs(response),1e-30)),
                          calc_phase_deg=math.degrees(math.atan2(response.imag,response.real)),valid=False)
                for key,scale in (('main',1.),('half',.5)):
                    try:
                        data[key]=one_stage(base/f'fra-{i}-{key}',p,op,label+f' · FRA {hz:g} Hz {key}',
                                            fra_hz=hz,fra_amplitude=peak_amplitude*scale)['fra']
                    except CalculationCancelled:
                        raise
                    except Exception as error:
                        data['error']=str(error)
                if data.get('main') and data.get('half'):
                    data['gain_delta_db']=abs(data['main']['gain_db']-data['half']['gain_db'])
                    data['phase_delta_deg']=abs((data['main']['phase_deg']-data['half']['phase_deg']+180)%360-180)
                    data['valid']=bool(data['gain_delta_db']<=1 and data['phase_delta_deg']<=8)
                if data.get('main'):
                    data['calculation_gain_error_db']=data['main']['gain_db']-data['calc_db']
                    data['calculation_phase_error_deg']=(data['main']['phase_deg']-data['calc_phase_deg']+180)%360-180
                row['fra'].append(data)
            row['fra_status']='完成' if all(point['valid'] for point in row['fra']) else '需复核'
            return row

        worker_count=endpoint_workers(len(cases),settings['simulation_threads'],parallel=parallel)
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            results=list(pool.map(one_case,boundaries))
        if cancelled():
            raise CalculationCancelled()
        evidence=dict(schema='powerdesign-spice-comparison-2',topology='LLC',
                      model='llc-switched-1', input_fingerprint=input_fingerprint(bundle['base_spec']),
                      settings=settings,cases=results)
        pending_zip,pending_word,pending_xlsx = (root/'comparison.zip',root/'comparison.docx',root/'comparison.xlsx')
        with zipfile.ZipFile(pending_zip,'w',zipfile.ZIP_DEFLATED) as output:
            output.writestr('comparison.json',_json(evidence))
            for case in _cases(bundle):
                for file in sorted((root/case['id']).rglob('*')):
                    if file.is_file() and file.suffix.lower() not in ('.raw','.op.raw'):
                        output.write(file,file.relative_to(root).as_posix())
        try:
            export_comparison(pending_word,results)
            write_llc_comparison_xlsx(pending_xlsx,evidence)
        except Exception as error:
            recovery=destination.with_name(f'{destination.stem}-evidence-{time.time_ns()}.zip')
            pending_zip.replace(recovery)
            raise RuntimeError(f'报告排版未完成，实际仿真证据已保留：{recovery}') from error
        with zipfile.ZipFile(pending_zip,'a',zipfile.ZIP_DEFLATED) as output:
            output.write(pending_word,report_file.name)
            output.write(pending_xlsx,xlsx_file.name)
        if cancelled():
            raise CalculationCancelled()
        pending_xlsx.replace(xlsx_file)
        pending_word.replace(report_file)
        pending_zip.replace(zip_file)
    good=sum(row['status']=='完成' for row in results)
    fra_good=sum(row['fra_status']=='完成' for row in results)
    fra_count=len(cases) if settings['fra_enabled'] else 0
    return dict(path=str(report_file),report_path=str(report_file),xlsx_path=str(xlsx_file),zip_path=str(zip_file),
                successful=good,total=len(results),
                incomplete=good<len(results) or any(row['dynamic_status']!='完成' for row in results)
                           or fra_good<fra_count,
                fra_successful=fra_good,fra_total=fra_count,cross_successful=0,cross_total=0)
