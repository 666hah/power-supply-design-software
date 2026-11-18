"""Fixed-hardware endpoint selection and 10% to 90% load transients."""
import json
import math
import re

import numpy as np


def voltages(parameters):
    nominal = parameters['V_in']
    low = float(parameters.get('V_in_min', nominal))
    high = float(parameters.get('V_in_max', low))
    return [low] if math.isclose(low, high, rel_tol=1e-12) else [low, high]


def endpoint_cases(parameters, cases):
    selected = []
    for voltage in voltages(parameters):
        match = next((case for case in cases if math.isclose(case['voltage'], voltage, rel_tol=1e-12)), None)
        if match is None:
            raise ValueError(f'缺少 {voltage:g} V 边界的设计计算，请先计算输入端点')
        selected.append(match)
    return selected


def load_fractions(rail, settings):
    return .1, .9, '额定负载 10% ↔ 90%'


def load_definition(parameters, settings):
    from isolated_outputs import output_specs
    rails = output_specs(parameters)
    feedback = int(parameters.get('feedback_output', 1)) if rails else 1
    rail = rails[feedback-1] if rails else parameters
    power = float(rail['P_out'])
    low,high,source = load_fractions(rail,settings)
    first = settings['step_ms']*.001
    hold = (settings['stop_ms']-settings['step_ms'])*.001
    return dict(feedback_output=feedback, output_count=len(rails) or 1, reference_v=abs(float(rail['V_out'])),
                rated_power_W=power, low_fraction=low, high_fraction=high,
                selection=source, stop_s=first+2*hold,
                stimulus=[dict(rail=feedback, time_s=first, before=low, after=high),
                          dict(rail=feedback, time_s=first+hold, before=high, after=low)])


def prepare_load_deck(files, definition, *, cot=False, slew_s=1e-6):
    from spice_studies import override_parameters
    stop = definition['stop_s']
    updates = dict(TEND=stop, AFTER=1., SHUTDOWN=0.) if cot else dict(TSTOP=stop, LOAD_AFTER=1., SHORT_EN=0.)
    result = override_parameters(files, updates)
    stage = result['power_stage.inc'].decode('ascii')
    rail = definition['feedback_output']
    reference = 'B_LOAD' if cot else f'BLOAD{rail}'
    expression = f'{definition["low_fraction"]:.12g}'
    for event in definition['stimulus']:
        expression += f'+({event["after"]-event["before"]:.12g})*limit((time-{event["time_s"]:.12g})/{slew_s:.12g},0,1)'
    pattern = rf'(?m)^({reference}\s+[^\r\n]+?)\*\(1\+\([^\r\n]+$'
    stage, count = re.subn(pattern, lambda match: match[1]+'*('+expression+')', stage)
    if count != 1:
        raise ValueError(f'未识别唯一反馈路负载 {reference}，不运行阶跃测试')
    result['power_stage.inc'] = stage.encode('ascii')
    analysis = files['analysis.inc'].decode('ascii')
    commands = [line for line in analysis.splitlines() if line.lower().startswith(('.options ', '.tran '))]
    if not any(line.lower().startswith('.tran ') for line in commands):
        raise ValueError('未取得原有开关模型的瞬态求解设置')
    commands = [re.sub(r'(?i)\s+plotwinsize\s*=\s*\S+','',line) for line in commands]
    commands.append('.options plotwinsize=0')
    outputs = ' '.join(f'V(out{i})' for i in range(1, definition.get('output_count', 1)+1))
    commands.append(f'.save {outputs}'+('' if cot else ' V(sgnd)')+
                    (' V(fault)' if re.search(r'\bV\(fault\)',analysis,re.I) else ''))
    result['analysis.inc'] = ('\n'.join(commands)+'\n').encode('ascii')
    result['stimulus.json'] = json.dumps(definition,ensure_ascii=False,indent=2).encode('utf-8')
    return result


def run_load_transient(files, case, settings, folder, execute, *, cot=False, frequency_hz=None):
    from calculation_scheduler import CalculationCancelled
    from spice_runtime import TransientRaw, read_log
    from spice_studies import write_study
    from spice_black_box import measure_load_steps
    parameters = case['p']
    definition = load_definition(parameters, settings)
    config = (parameters.get('cot_config') or {}) if cot else {}
    slew = max(float(config.get('load_rise_s', 1e-6)),1e-9)
    definition.update(slew_s=slew, load_model='恒流' if config.get('load_mode')=='current' else '恒阻',
                      other_outputs='其余输出保持各自满载')
    result = dict(definition, complete=False, available=False, events=[])
    try:
        prepared = prepare_load_deck(files,definition,cot=cot,slew_s=slew)
        write_study(folder, prepared, '# 反馈路 10% ↔ 90% 双向阶跃\n\n额定负载比例、边沿时刻和斜率见 stimulus.json。'
                    '其余输出保持满载；本实验不注入短路或关机事件。\n')
        result['elapsed_s'] = execute(folder, settings['simulation_timeout_s'])
        _, _, errors, _ = read_log(folder/'Flyback.log')
        if errors:
            raise ValueError('；'.join(errors[:4]))
        raw = TransientRaw(folder/'Flyback.raw')
        try:
            if not math.isclose(raw.time[-1],definition['stop_s'],rel_tol=1e-7,abs_tol=1e-10):
                raise ValueError('双向阶跃记录未到达设定终点')
            first, second = definition['stimulus']
            key = f'v(out{definition["feedback_output"]})'
            reference = None if cot else 'v(sgnd)'
            out_names = [f'v(out{i})' for i in range(1, definition['output_count']+1)]
            sampled = raw.plot_samples({name:(name,reference) for name in out_names},
                max(0.,first['time_s']-.1*(second['time_s']-first['time_s'])),definition['stop_s'],
                markers=[e['time_s']+dt for e in definition['stimulus'] for dt in (0.,slew)])
            time = np.asarray(sampled['time'])
            load = np.full_like(time,definition['low_fraction'])
            for event in definition['stimulus']:
                load += (event['after']-event['before'])*np.clip((time-event['time_s'])/slew,0,1)
            values = np.asarray(sampled[key])
            rated_current = definition['rated_power_W']/definition['reference_v']
            current = rated_current*load
            if result['load_model'] == '恒阻':
                current *= values/definition['reference_v']
            result['waveform'] = dict(time=sampled['time'],voltage=sampled[key],load_fraction=load.tolist(),
                load_current_A=current.tolist(), ports={str(i):sampled[name] for i,name in enumerate(out_names,1)})
            if 'v(fault)' in raw.names and np.any(raw.trace('v(fault)')>=.5):
                raise ValueError('测试中观察到故障关断；不作正常负载响应判定')
            result.update(measure_load_steps(raw,definition['stimulus'],reference_v=definition['reference_v'],
                          frequency_hz=frequency_hz or case['result']['op']['f_sw'],stop_s=definition['stop_s'],
                          return_node=reference,band_pct=(config.get('acceptance') or {}).get('settling_band_pct',2.)))
            from isolated_outputs import output_specs
            result['response_by_port']={str(definition['feedback_output']):result['events']}
            for rail, spec in enumerate(output_specs(parameters),1):
                if rail==definition['feedback_output']:continue
                observed=[dict(event,rail=rail) for event in definition['stimulus']]
                response=measure_load_steps(raw,observed,reference_v=abs(float(spec['V_out'])),
                    frequency_hz=frequency_hz or case['result']['op']['f_sw'],stop_s=definition['stop_s'],
                    return_node=reference,band_pct=result['band_pct'])
                result['response_by_port'][str(rail)]=response['events']
            result['complete'] = bool(result['available'])
            if not result['complete']:
                result['error'] = result.get('reason') or '未取得两次有效的负载边沿'
        finally:
            raw.close()
    except CalculationCancelled:
        raise
    except (ValueError,KeyError,RuntimeError,OSError) as exc:
        result.update(reason=str(exc),error=str(exc))
    if parameters.get('topology')=='QR-FLYBACK' and result.get('waveform'):
        from design_engine.contracts import json_value
        from loop_load_step import feedback_load_step
        from plants import build_loop_models
        try:
            operating_point=case['result']['op']
            models=case.get('models') or build_loop_models(parameters,operating_point)[0]
            result['design_step']=(json_value(feedback_load_step(parameters,models,operating_point)) if models else
                dict(available=False,reason='当前设计工作点未取得环路模型'))
        except (ValueError, KeyError, RuntimeError, ArithmeticError) as exc:
            result['design_step']=dict(available=False,reason=str(exc))
    return result
