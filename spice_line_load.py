"""One combined input/load boundary study for the common switching decks."""
import math
import re

from spice_studies import override_parameters, write_study


def prepare_line_load(files, rails, voltages, settings, frequency, *, input_hold_s=.5, tail_s=.05):
    from spice_boundary import load_fractions
    low, high = min(voltages), max(voltages)
    start = settings['step_ms'] * .001
    first_edge = start + input_hold_s
    second_edge = first_edge + input_hold_s
    stop = second_edge + tail_s
    prepared = override_parameters(files, dict(TSTOP=stop, SHORT_EN=0, LOAD_AFTER=1))
    stage = prepared['power_stage.inc'].decode('ascii')
    source = f'VIN_SOURCE input 0 PWL(0 {low:.12g} {first_edge:.12g} {low:.12g} {first_edge+1e-6:.12g} {high:.12g} {second_edge:.12g} {high:.12g} {second_edge+1e-6:.12g} {low:.12g})'
    stage, count = re.subn(r'(?im)^VIN_SOURCE input 0 \{VIN\}[ \t]*$', source, stage)
    if count != 1:
        raise ValueError('输入源不支持此联合激励')
    if low != high and b'.param VM={RAMP_RATIO*' in files['design_params.inc']:
        library = prepared['GenericBuckBoostPWM.lib'].decode('ascii')
        stage, ports = re.subn(r'(?m)^(XU_CTRL .*? fault 0) GNISO_CTRL ',r'\1 vin_bus GNISO_CTRL ',stage)
        library, wrapper = re.subn(r'(?im)^(\.subckt GNISO_CTRL(?:_FAST|_FULL)? .*? FAULT COM) params:',r'\1 VIN_FF params:',library)
        library, core = re.subn(r'(?im)^(\.subckt GNISO_CORE .*? ILIM COM) params:',r'\1 VIN_FF params:',library)
        library, calls = re.subn(r'(?im)^(Xcore .*? ilim COM) GNISO_CORE ',r'\1 VIN_FF GNISO_CORE ',library)
        ramp = '{VM}*{FSW}*V(age,COM)'
        if (ports,wrapper,core,calls,library.count(ramp))!=(1,2,1,2,1):
            raise ValueError('Buck 输入前馈接口与模型不匹配，未运行线载联合试验')
        prepared['GenericBuckBoostPWM.lib']=library.replace(ramp,'V(VIN_FF,COM)*{RAMP_RATIO}*{FSW}*V(age,COM)').encode('ascii')
    probes = ['V(input)', 'V(sgnd)', 'V(fault)']
    measures = []
    schedule = []
    for index, rail in enumerate(rails, 1):
        power = float(rail['P_out'])
        lower, upper, _ = load_fractions(rail,settings) if power else (0.,0.,'')
        dwell = .009 + .001*index
        stage += f'\nVpattern{index} lpatt{index} 0 PULSE({lower:.12g} {upper:.12g} {start:.12g} 1u 1u {dwell-1e-6:.12g} {2*dwell:.12g})\n'
        stage, count = re.subn(rf'(?im)^BLOAD{index} .*$', f'BLOAD{index} out{index} sgnd I=V(out{index},sgnd)/{{RLOAD{index}}}*V(lpatt{index})',stage)
        if count != 1:
            raise ValueError(f'OUT{index} 负载探针与网表不一致')
        probes.append(f'V(out{index})')
        probes.append(f'V(lpatt{index})')
        for suffix, operation in [('min','MIN'),('max','MAX')]:
            measures.append(f'.meas TRAN port{index}_{suffix} {operation} V(out{index},sgnd) FROM {start:.12g} TO {stop:.12g}')
            measures.append(f'.meas TRAN patt{index}_{suffix} {operation} V(lpatt{index}) FROM {start:.12g} TO {stop:.12g}')
        schedule.append(dict(rail=index, low_fraction=lower, high_fraction=upper, dwell_ms=round(dwell*1000)))
    measures += [f'.meas TRAN fault_max MAX V(fault) FROM {start:.12g} TO {stop:.12g}',
                 f'.meas TRAN line_low FIND V(input) AT {start+input_hold_s/2:.12g}',
                 f'.meas TRAN line_high FIND V(input) AT {first_edge+input_hold_s/2:.12g}',
                 f'.meas TRAN line_end FIND V(input) AT {second_edge+tail_s/2:.12g}']
    prepared['power_stage.inc'] = stage.encode('ascii')
    original = files['analysis.inc'].decode('ascii').splitlines()
    options = [re.sub(r'(?i)\s+plotwinsize\s*=\s*\S+','',line) for line in original if line.lower().startswith('.options ')]
    tran = next((line.split() for line in original if line.lower().startswith('.tran ')),[])
    if len(tran)<5:
        raise ValueError('未取得原网表的开关求解步长')
    tran[2:4]=[f'{stop:.12g}','0']
    prepared['analysis.inc'] = ('\n'.join([*options,'.options plotwinsize=0',' '.join(tran), '.save '+' '.join(probes), *measures])+'\n').encode('ascii')
    return prepared, schedule


def run_line_load(files, rails, voltages, settings, frequency, folder, execute, *, prepare=prepare_line_load,
                  input_hold_s=.5, tail_s=.05):
    from calculation_scheduler import CalculationCancelled
    from spice_runtime import TransientRaw, read_log, partial_transient_time
    start = settings['step_ms']*.001
    first_edge, second_edge = start+input_hold_s, start+2*input_hold_s
    result = dict(complete=False, voltages=sorted(set(voltages)), rows=[], input_hold_s=input_hold_s,
                  tail_s=tail_s, stimulus_start_s=start)
    try:
        if not all(math.isfinite(t) and t>2e-6 for t in (input_hold_s,tail_s)):
            raise ValueError('输入档与返回档的驻留时间必须大于激励边沿')
        extra = {} if (input_hold_s,tail_s)==(.5,.05) else dict(input_hold_s=input_hold_s,tail_s=tail_s)
        prepared, result['schedule'] = prepare(files, rails, voltages, settings, frequency,**extra)
        write_study(folder,prepared,f'# 线载联合动态稳定度\n输入依次驻留 {input_hold_s*1000:g}、{input_hold_s*1000:g} 和 {tail_s*1000:g} ms。各路负载等效电阻按额定电压折算，两方向边沿 1 µs。\n')
        result['elapsed_s'] = execute(folder,settings['cross_timeout_s'])
        values, _, errors, _ = read_log(folder/'Flyback.log')
        has_fault = bool(re.search(rb'(?im)^\.meas\s+tran\s+fault_max\b',prepared['analysis.inc']))
        required = ['line_low','line_high','line_end'] + (['fault_max'] if has_fault else []) + [f'{prefix}{index}_{suffix}' for prefix in ('port','patt') for index in range(1,len(rails)+1) for suffix in ('min','max')]
        if errors or not all(math.isfinite(values.get(key,float('nan'))) for key in required):
            raise ValueError('；'.join(errors[:2]) or '缺少完整观察窗口的测量值')
        finish = partial_transient_time(folder/'Flyback.raw')
        result['actual_end_s']=finish
        if finish is None or not math.isclose(finish, second_edge+tail_s, rel_tol=1e-7,abs_tol=1e-10):
            raise ValueError('原始波形没有覆盖完整线载激励观察窗')
        result.update(actual_end_s=finish,line_plateaux_V=[values[key] for key in ('line_low','line_high','line_end')])
        def matches(measure,expected):
            return math.isclose(measure,expected,rel_tol=1e-4,abs_tol=1e-6)
        if not all(matches(measure, expected) for measure,expected in
                   zip(result['line_plateaux_V'],(min(voltages),max(voltages),min(voltages)))):
            raise ValueError('测得输入平台与低→高→低边界不符')
        for row in result['schedule']:
            index = row['rail']
            if not all(matches(values[f'patt{index}_{suffix}'],row[key]) for suffix,key in
                       [('min','low_fraction'),('max','high_fraction')]):
                raise ValueError(f'OUT{index} 未观察到完整负载激励范围')
        result.update(complete=True, protection=values['fault_max']>=.5 if has_fault else None,protection_available=has_fault,
                      rows=[dict(rail=index, min_V=values[f'port{index}_min'],max_V=values[f'port{index}_max']) for index in range(1,len(rails)+1)])
        try:
            raw = TransientRaw(folder/'Flyback.raw')
            try:
                reference = 'v(sgnd)' if 'v(sgnd)' in raw.names else None
                signals = {'input_V':('v(input)',None)}
                signals.update({f'out{i}':(f'v(out{i})',reference) for i in range(1,len(rails)+1)})
                signals.update({f'load{i}':(f'v(lpatt{i})',None) for i in range(1,len(rails)+1)})
                plot = raw.plot_samples(signals,start,finish,markers=[first_edge,first_edge+1e-6,second_edge,second_edge+1e-6])
                result['waveform'] = dict(time=plot['time'],input_V=plot['input_V'],
                    ports={str(i):plot[f'out{i}'] for i in range(1,len(rails)+1)},
                    load_fraction={str(i):plot[f'load{i}'] for i in range(1,len(rails)+1)})
            finally:
                raw.close()
        except (KeyError, ValueError, OSError) as exc:
            result['waveform_error'] = str(exc)
    except CalculationCancelled:
        raise
    except (KeyError,ValueError,RuntimeError,OSError,TimeoutError) as exc:
        result['error'] = str(exc)
    return result
