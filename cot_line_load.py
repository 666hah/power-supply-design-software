"""COT fixture adapter for the common line/load stability test."""
import re

from spice_line_load import prepare_line_load
from spice_studies import override_parameters


def prepare_cot_line_load(files, rails, voltages, settings, frequency):
    if len(rails)!=1:
        raise ValueError('COT 稳定度试验需要单个反馈端口')
    low, high = min(voltages),max(voltages)
    adapted=override_parameters(files,dict(VIN=high,SHUTDOWN=0,AFTER=1))
    stage=adapted['power_stage.inc'].decode('ascii')
    source=re.search(r'(?im)^VIN_SOURCE input 0 (?:\{VIN\}|PWL\(0 0 ([\d.e+-]+) \{VIN\}\))$',stage)
    load=re.search(r'(?m)^B_LOAD out1 0 I=(.+?)\*\(1\+\(AFTER-1\)\*limit\(.+$',stage)
    if source is None or load is None:
        raise ValueError('未识别 COT 输入或额定负载，未改变被测电路')
    configured_rise=source[1]
    adapted['power_stage.inc']=stage.replace(source[0],'VIN_SOURCE input 0 {VIN}').replace(load[0],'BLOAD1 out1 sgnd I=0').encode('ascii')
    prepared,schedule=prepare_line_load(adapted, rails, voltages, settings, frequency)
    stage=prepared['power_stage.inc'].decode('ascii')
    stage,count=re.subn(r'(?m)^BLOAD1 [^\n]*','B_LOAD out1 0 I='+load[1]+'*V(lpatt1)',stage)
    if count!=1:
        raise ValueError('COT 负载转换失败')
    if configured_rise:
        if float(configured_rise)>settings['step_ms']*.001:
            raise ValueError('输入启动斜率尚未完成，请延长阶跃前观察时间')
        stage=stage.replace(f'PWL(0 {low:.12g} ',f'PWL(0 0 {configured_rise} {low:.12g} ')
    control=prepared['control.inc'].decode('ascii')
    if low!=high:
        if 'B_BASETON ' not in control:
            if 'delay(V(ticks),{TON})' not in control:
                raise ValueError('未取得 COT 脉宽接口，不能生成输入跨端点的试验')
            control=control.replace('delay(V(ticks),{TON})',
                'delay(V(ticks),V(baseton),{max(FIXEDTON,1/FREF)})').replace('FMAX','V(maxrate)')
            control+='\nB_BASETON baseton 0 V=if(FIXEDTON>0,FIXEDTON,VSET/(max(V(vbus),VSET+1m)*FREF))\n'
            control+='B_MAXRATE maxrate 0 V=min(FREQCAP,1/(V(baseton)+max(TOFFMIN,OFF_FLOOR)))\n'
        else:
            control=control.replace('V=min(FMAX,1/(V(baseton)','V=min(FREQCAP,1/(V(baseton)')
        control=control.replace('*FBIAS','*V(linebias)')
        control+='\nB_LINEBIAS linebias 0 V=(VSET+IREF*(RL+DCR))/(max(V(vbus)-IREF*(RH-RL),VSET/2)*V(baseton))\n'
    analysis=prepared['analysis.inc'].decode('ascii').replace(' V(sgnd)','').replace('V(out1,sgnd)','V(out1)')
    if 'v(fault)' not in files['analysis.inc'].decode('ascii').lower():
        analysis='\n'.join(line.replace(' V(fault)','') for line in analysis.splitlines()
                           if not line.startswith('.meas TRAN fault_max'))+'\n'
    prepared.update({'analysis.inc':analysis.encode('ascii'),'control.inc':control.encode('ascii'),
                     'power_stage.inc':stage.encode('ascii')})
    return prepared,schedule
