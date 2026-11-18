"""Compose one actual switching-circuit experiment from the DC power canvas.

All positive ports share the explicitly declared return 0. Existing converter
decks own their magnetics, capacitors, switching control and protection; this
module owns only sources, interconnects, external enable and terminal loads.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from system_sequence_config import normalize as config_for,nominal_ports
from system_sequence_behavior import protected_source, staged_load


def _f(value):return format(float(value),'.12g')


def _ldo(spec,namespace,config):
    from ldo import normalize
    p=normalize(spec);name=namespace+'_UNIT';r=config['ldo_output_resistance_ohm']
    limit=config['ldo_output_current_limit_A'];gate='V(en)' if p['enable_pin'] else '1'
    iq_voltage=max(float(p.get('input_rating_min') or p['dropout_max'] or .1),.1)
    reference=_f(p['V_out']);timing=[]
    if config['soft_start_s'] is not None:
        run=f'if({gate}>.5,1,0)' if p['enable_pin'] else f'if(V(input)>{_f(iq_voltage)},1,0)'
        timing=[f'Bssrun ssrun 0 V={run}','Cssage ssage 0 1u',
            'Bssage 0 ssage I=if(V(ssrun)>.5,1u,0)','Sssreset ssage 0 0 ssrun SEQ_TIMER']
        reference=f'{reference}*limit(V(ssage)/{_f(config["soft_start_s"])},0,1)'
    target=f'max(0,min({reference},V(input)-{_f(p["dropout_max"])}))'
    current=f'max(({target}-V(cap1))/{_f(r)},0)'
    if limit is not None:current=f'min({current},{_f(limit)})'
    lines=[f'.subckt {name} input en vcc out1',*timing,
        f'Bpass input cap1 I=if({gate}>.5,{current},0)',
        f'Biq input 0 I={_f(p["Iq_max"])}*limit(V(input)/{_f(iq_voltage)},0,1)',
        f'Cinput input 0 {_f(p["C_in"])} Rser=.01',
        f'Coutput cap1 0 {_f(p["C_out"])} Rser={_f(max(p["ESR_out"],1e-6))}',
        'Voutput cap1 out1 0','Roff cap1 0 1e9',f'.ends {name}']
    limitations=['LDO为静态压差/有限输出电阻行为近似，不是厂家内部环路、启动、热保护或反向电流模型。',
        'LDO等效输出电阻为用户配置的工程假设，额定电流不作为未知的限流门限。']
    if limit is None:limitations.append('LDO未填写真实输出限流，模型不限制通过电流，不能判其过流保护合格。')
    if not p['enable_pin']:limitations.append('该LDO未声明EN引脚，输出跟随输入压差；画布使能时刻不会虚构一个物理EN。')
    limitations.append('LDO反向导电/反灌未建模；预偏置和掉电反向电流需单独验证。')
    limitations.append(f'LDO静态电流在0至{iq_voltage:g}V间按电压线性缩放，以上为配置Iq；低压段仅为合规假设，不是芯片UVLO或实测曲线。')
    if timing:limitations.append('LDO按配置软启动时间线性提升参考电压；恒定限流、线性软启均为行为近似，未模拟实际折返及内部环路。')
    return dict(subckt_text='\n'.join(lines)+'\n',libraries={},output_count=1,
        outputs=[dict(id=1,name='LDO',V_out=p['V_out'],P_out=p['P_out'],out_node='out1',cap_node='cap1')],
        probes=dict(input='input',inputbus='input',en='en',vcc='vcc',cap1='cap1',out1='out1'),
        manifest=dict(topology='LDO',resolved_controller={},sequence_unit=dict(subckt_name=name,
            thresholds=dict(nominal_vcc_v=1.,cycle_cs_ceiling_v=None,sense_resistor_ohm=None,iq_compliance_voltage_v=iq_voltage,soft_start_s=config['soft_start_s']),
            limitations=limitations,model_level='linear-regulator-behavior')))


def project_files(project,*,cancelled=lambda:False,progress=None):
    import power_network as net
    from power_units import load_unit
    from system_sequence_units import compile_unit
    from calculation_scheduler import CalculationCancelled
    p=net.normalize(project);cfg=config_for(p);s=cfg['settings'];ports=nominal_ports(p,s['vin_case'])
    def check():
        if cancelled():raise CalculationCancelled()
    check()
    if not p['sources']:raise ValueError('联合启停至少需要一个外部输入源')
    safe={n['id']:f'N{i:03d}' for i,(_,n) in enumerate(net.nodes(p),1)}
    unit_names={n['id']:f'U{i:02d}' for i,n in enumerate(p['units'],1)}
    port_nodes={n['id']:safe[n['id']] for n in p['sources']+p['junctions']+p['loads']}
    for n in p['units']:
        for i,_ in enumerate(n['rails'],1):port_nodes[f'{n["id"]}/OUT{i}']=unit_names[n['id']]+f'_OUT{i}'
    lines=['* Power canvas: actual switching units, explicit common DC return 0.',
        '* Source/connection impedances are configured engineering assumptions.',
        '.model SEQ_D D(Ron=.01 Roff=1e12 Vfwd=0)',
        '.model SEQ_SOURCE_D D(Ron=1u Roff=1e12 Vfwd=0)',
        '.model SEQ_TIMER SW(Ron=.01 Roff=1e12 Vt=-.5 Vh=.01)']
    files={};save=[];source_caps=[];manifest=dict(schema='power.system-sequence-evidence/1',settings=copy.deepcopy(s),
        configuration=cfg,sources={},units={},loads={},connections={},ports={},limitations=[
        '实际运行原创通用开关级SPICE模型；不是原厂硅片或实测，不据模型完成判整机合格。',
        '画布仅有正供电线，所有单元使用公共返回0；未验证隔离侧接地、地弹、安规或实际回路寄生。',
        '源默认50mΩ、连接默认10mΩ仅为工程假设；修改为实测阻抗后再判浪涌。源保护按各源明确配置：monitor仅比较；cc/foldback/hiccup为工程行为，不代表已核实的实物。',
        '控制器VCC默认独立理想电源，未模拟辅助绕组接管和偏置供电功耗。输入UVLO与VCC欠压是不同门限。',
        '保留每单元实际Cin/Cout：EN关闭也会充输入电容，关机后输出按电路自行放电。额外负载C只按显式配置添加。',
        '有声明下级连接的输出不再放置额定测试负载；无连接端口默认额定CR负载，用户可另行停用或修改。',
        '纯二极管OR按实际瞬时电压/Vf/支路R分流，不假定同压理想均流；未建模主动MUX的优先级/切换空窗。',
        '连接二极管采用LTspice分段线性模型：Ron=1mΩ、Roff=1TΩ，Vf沿用支路配置；仅在10µV转折区二次平滑，以避免OR近零供流及残压恢复时的数值卡点。该有限膝区属于模型近似，保留设定Vf及膝区外的正反向斜率，不放宽求解容差，不等同实测二极管曲线。'])
    manifest['interconnect_model']=dict(version='sequence-diode-1.2',diode_on_resistance_ohm=.001,
        diode_off_resistance_ohm=1e12,diode_transition_V=1e-5)
    manifest['limitations'].append('外部源默认不吸收回流，用零Vf/1μΩ理想阻断近似；允许反向吸流时PWL电压源可吸收电容能量。这是源端能力假设，不是所有实际电源的验证。')
    def probe(node):
        text='V('+node+')';save.append(text);return text
    def current(element):
        text='I('+element+')';save.append(text);return text
    def schmitt(identity,node,on,off):
        state=identity+'_state'
        if on is None:lines.append('V'+identity+'_READY '+state+' 0 1')
        else:lines.append(f'A{identity} {node} 0 0 0 0 0 {state} 0 SCHMITT Vt={_f((on+off)/2)} Vh={_f((on-off)/2)} Vhigh=1 Vlow=0 Td=10n Trise=10n Tfall=10n')
        return state
    def timer(identity,ready):
        # Finite-state capacitor timer: 1uA / 1uF = 1V/s. Unlike an idt reset
        # assertion, rejected Newton trial voltages cannot reset its history.
        # Reset time constant is 10ns; it is a logic surrogate, not bus energy.
        age=identity+'_age'
        lines.extend([f'C{identity}_TIMER {age} 0 1u',f'B{identity}_TIMER 0 {age} I=if(V({ready})>.5,1u,0)',
            f'S{identity}_RESET {age} 0 0 {ready} SEQ_TIMER'])
        return age
    def ready_conditions(identity, rows):
        conditions=[]
        for index, condition in enumerate(rows,1):
            if condition['port'] not in port_nodes:raise ValueError(identity+'就绪端口不存在：'+condition['port'])
            state=schmitt(identity+'_COND'+str(index),port_nodes[condition['port']],condition['on_V'],condition['off_V'])
            conditions.append(f'(V({state})>.5)')
        return '&'.join(conditions) or '1'
    # Supply ramp and finite source impedance apply independently of enables.
    for i,n in enumerate(p['sources'],1):
        check();identity=n['id'];row=cfg['sources'][identity];v=n[s['vin_case']] if n['enabled'] else 0.
        name=f'S{i:02d}';port=safe[identity];b=name+'_internal'
        capacitance=row.get('output_capacitance_F',0.)
        a=port
        points=[(0,0),(row['on_s'],0),(row['on_s']+row['rise_s'],v),(row['off_s'],v),(row['off_s']+row['fall_s'],0)]
        if row['voltage_profile']:points=[(item['time_s'],item['level']*v) for item in row['voltage_profile']]
        collapsed=[]
        for t,x in points:
            if collapsed and t==collapsed[-1][0]:collapsed[-1]=(t,x)
            else:collapsed.append((t,x))
        lines.append(f'V{name} {b} 0 PWL('+ ' '.join(_f(t)+' '+_f(x) for t,x in collapsed)+')')
        source_probes={}
        if row['protection_mode']=='monitor':
            supply=b
            if not row['sink_current']:
                supply=name+'_blocked';lines.append(f'D{name}_BLOCK {b} {supply} SEQ_SOURCE_D')
            end=a
            if row['inductance_H']>0:
                end=name+'_rl';lines.append(f'L{name} {end} {a} {_f(row["inductance_H"])}')
            lines.append(f'R{name} {supply} {end} {_f(row["resistance_ohm"])}')
        else:
            nodes=protected_source(lines,name,b,a,row,timer)
            source_probes=dict(limit_active_probe=probe(nodes['limit']),fault_probe=probe(nodes['fault']))
            manifest['limitations'].append(identity+'源保护为有限R的CV/限流行为特性；转折使用单调平滑，较理想夹限误差不超过当前限值的0.1%，不超限、不吸流源无反向电流。限流状态指请求电流达到限值，此时实际约99.90005%限值。无真实控制环带宽/传播延时；打嗝按连续限流延时关闭并定时重试，命令电压低于1mV复位。主动模式暂不支持源串L，避免未定义续流。')
            if row['sink_current']:manifest['limitations'].append(identity+'双向源在吸流时按对称限流，打嗝断开两个方向；须核实实物具备该能力。')
        if capacitance>0:
            source_caps.append(f'C{name}_OUTPUT {a} 0 {_f(capacitance)} Rser={_f(row["output_esr_ohm"])}')
            source_probes.update(port_current_derivation='source-minus-capacitor',
                output_capacitor_current_probe=current('C'+name+'_OUTPUT'))
            manifest['limitations'].append(identity+'源端输出电容在限流/阻断之后，断供时保留储能；原源电流探针测限流器供流（含给此C充电），端口电流按源供流减C充电电流由完整RAW计算，不串入额外传感元件。C可短时补充电流，两者不可互作限流判断；C/ESR需实测或标明工程假设。')
        manifest['sources'][identity]=dict(name=n['name'],voltage_probe=probe(port),current_probe=current('V'+name),capacity_W=n['capacity'],config=copy.deepcopy(row),**source_probes)
    frequencies=[]
    unit_maxsteps=[]
    for i,n in enumerate(p['units'],1):
        check();identity=n['id'];name=unit_names[identity];row=cfg['units'][identity]
        if progress:progress('准备开关电路：'+identity+' · '+n['name'])
        spec=copy.deepcopy(load_unit(n['spec']))
        if spec.get('topology')!='LDO':
            settings=copy.deepcopy(spec.get('spice_config') or {})
            if spec.get('topology') in ('BUCK','BOOST'):
                # DCM with all switch-node capacitances removed leaves L
                # discharging through GOhm off-state impedances (fs-scale L/R).
                # Preserve the declared component energy storage for the
                # system transient; never invent C or mutate the saved unit.
                retain_caps=s.get('include_switching_capacitance',True)
                prior_mode=settings.get('niso_edge_model',0.)
                if retain_caps:settings['niso_edge_model']=1.
                manifest['limitations'].append(identity+(
                    '联合启停保留单元已填常数Coss、Qg/Vgs等效栅电容及控制器Cj假设，避免DCM截止区完全无储能的刚性；不改保存的单元设置，不等于验证真实开关损耗。'
                    if retain_caps else '联合启停按用户选择沿用单元独立寄生模式；若Coss/Cg/Cj全关闭，DCM电流归零时可能极小时间步或超时。'))
            if row['soft_start_s'] is not None:settings['soft_start_ms']=row['soft_start_s']*1000
            # These standalone test times are discarded by compile_unit, but
            # must still satisfy its controller-configuration validation.
            ss=float(settings.get('soft_start_ms',1.))
            settings['step_ms']=max(float(settings.get('step_ms',8.)),ss+1.)
            settings['stop_ms']=max(float(settings.get('stop_ms',12.)),settings['step_ms']+1.)
            settings.update(short_test=0.,fra_enabled=0.,cross_enabled=0.,simulation_reuse=0.)
            spec['spice_config']=settings
            # Cancellation reaches the existing periodic solvers too.
            from input_voltage_range import _cancellation_scope
            with _cancellation_scope(cancelled):compiled=compile_unit(spec,name)
            if spec.get('topology') in ('BUCK','BOOST'):
                compiled['manifest']['sequence_unit']['switching_capacitance_policy']=dict(
                    retain_declared=retain_caps,original_unit_mode=prior_mode,
                    effective_mode=settings.get('niso_edge_model',0.),changes_saved_unit=False)
            controller=compiled['manifest']['resolved_controller']
            frequencies.append(max(float(controller.get('FSW',spec['f_sw'])),float(spec['f_sw'])))
            unit_step=compiled['manifest'].get('sequence_unit',{}).get('maximum_step_s')
            if unit_step:unit_maxsteps.append(float(unit_step))
        else:compiled=_ldo(spec,name,row)
        for filename,content in compiled['libraries'].items():files[filename]=content
        subfile=name+'_unit.inc';files[subfile]=compiled['subckt_text'].encode('ascii')
        lines.extend('.include '+fn for fn in compiled['libraries'])
        lines.append('.include '+subfile)
        incoming_node=safe[identity]+'_supply';unit_input=name+'_IN';en=name+'_EN';vcc=name+'_VCC'
        lines.append(f'V{name}_IN {incoming_node} {unit_input} 0')
        output_internal=[name+f'_internal_out{k}' for k in range(1,compiled['output_count']+1)]
        lines.append('X'+name+' '+' '.join([unit_input,en,vcc,*output_internal,compiled['manifest']['sequence_unit']['subckt_name']]))
        def absolute(value):
            if isinstance(value,dict):return {k:absolute(v) for k,v in value.items()}
            pins=dict(input=unit_input,en=en,vcc=vcc,**{f'out{k}':v for k,v in enumerate(output_internal,1)})
            if value in pins:return probe(pins[value])
            return probe('X'+name+':'+value)
        # Internal 1V/A current monitors and top-level 0V sensors avoid
        # ambiguous hierarchical I syntax without changing branch loading.
        pp={k:absolute(v) for k,v in compiled['probes'].items()}
        uvnode='X'+name+':'+compiled['probes']['inputbus']
        uv=schmitt('UV'+name,uvnode,row['vin_on_V'],row['vin_off_V'])
        pg='1'
        if row['wait_for_port']:
            if row['wait_for_port'] not in port_nodes:raise ValueError(identity+'等待的PG端口不存在，请修正启停配置')
            pg_node=port_nodes[row['wait_for_port']]
            if row['pg_hysteresis_V']>0:
                ready=schmitt(name+'_PG',pg_node,row['pg_threshold_V'],row['pg_threshold_V']-row['pg_hysteresis_V'])
            else:
                ready=name+'_PG_READY';lines.append(f'B{name}_PG {ready} 0 V=if(V({pg_node})>={_f(row["pg_threshold_V"])},1,0)')
            if row['ready_conditions']:
                extra=ready_conditions(name,row['ready_conditions'])
                combined=name+'_ALL_READY'
                lines.append(f'B{name}_ALL_READY {combined} 0 V=if((V({ready})>.5)&({extra}),1,0)')
                ready=combined
            age=timer(name+'_PG',ready)
            pp.update(pg_ready=probe(ready),pg_age=probe(age))
            pg=f'(V({ready})>.5)&(V({age})>={_f(row["pg_delay_s"])})'
        elif row['ready_conditions']:
            extra=ready_conditions(name,row['ready_conditions'])
            ready=name+'_ALL_READY';lines.append(f'B{name}_ALL_READY {ready} 0 V=if({extra},1,0)')
            age=timer(name+'_PG',ready)
            pp.update(pg_ready=probe(ready),pg_age=probe(age))
            pg=f'(V({ready})>.5)&(V({age})>={_f(row["pg_delay_s"])})'
        if row['ready_conditions']:manifest['limitations'].append(identity+'多轨就绪为外部电压监控AND/迟滞/连续达标延时，不等于真实芯片PG开漏引脚或其上拉电源。')
        lines.append(f'B{name}_EN {en} 0 V=if(({int(n["enabled"])})&(time>={_f(row["enable_s"])})&(time<{_f(row["disable_s"])})&(V({uv})>.5)&({pg}),1,0)')
        vg=compiled['manifest']['sequence_unit']['thresholds'].get('nominal_vcc_v',spec.get('Vgs',10.))
        if row['vcc_mode']=='ideal':lines.append(f'V{name}_VCC {vcc} 0 {_f(vg)}')
        else:lines.append(f'B{name}_VCC {vcc} 0 V={_f(vg)}*V({en})')
        outputs=[]
        for k,(local,o) in enumerate(zip(output_internal,compiled['outputs']),1):
            port=identity+'/OUT'+str(k);node=port_nodes[port];sensor='V'+name+f'_OUT{k}'
            lines.append(f'{sensor} {local} {node} 0')
            outputs.append(dict(id=k,name=o['name'],reference_V=o['V_out'],voltage_probe=probe(node),current_probe=current(sensor)))
        manifest['units'][identity]=dict(name=n['name'],instance='X'+name,compiled_manifest=compiled['manifest'],probes=pp,
            input_current_probe=current('V'+name+'_IN'),en_probe=probe(en),uvlo_probe=probe(uv),outputs=outputs,config=copy.deepcopy(row))
        if row['vin_on_V'] is None:manifest['limitations'].append(identity+'输入启停门限未配置：EN仅按时间/PG，本轮不判实际输入UVLO正确。')
        if row['vcc_mode']=='enable_follow':manifest['limitations'].append(identity+'理想VCC跟随EN，改变QR锁存复位条件；不是实际偏置供电。')
        manifest['limitations'].extend(identity+'：'+v for v in compiled['manifest']['sequence_unit'].get('limitations',[]))
    # External graph wiring: every branch has its own measured R/L and diode.
    for i,e in enumerate(p['connections'],1):
        if not e['enabled']:continue
        identity=e['id'];row=cfg['connections'][identity];name=f'E{i:03d}'
        a=port_nodes[net.port_key(e['source'])]
        b=safe[e['target']]+'_supply' if e['target'] in unit_names else port_nodes[e['target']]
        cursor=name+'_sense';lines.append(f'V{name} {a} {cursor} 0')
        if e['mode']=='diode':
            nxt=name+'_d';lines.append(f'D{name} {cursor} {nxt} {name}_D')
            lines.append(f'.model {name}_D D(Ron=.001 Roff=1e12 Vfwd={_f(e["vf"])} epsilon=10u)');cursor=nxt
        if row['inductance_H']>0:
            nxt=name+'_l';lines.append(f'L{name} {cursor} {nxt} {_f(row["inductance_H"])}');cursor=nxt
        lines.append(f'R{name} {cursor} {b} {_f(row["resistance_ohm"])}')
        manifest['connections'][identity]=dict(source=net.port_key(e['source']),target=e['target'],current_probe=current('V'+name),config=row)
    def add_load(key,node,row,enabled,nominal):
        if not row['enabled']:return
        name='LD'+str(len(manifest['loads'])+1).zfill(3);local=name+'_port';sensor='V'+name
        lines.append(f'{sensor} {node} {local} 0')
        state=schmitt(name,local,row['on_V'],row['off_V'])
        if not enabled:lines.append(f'B{name}_DISABLE {name}_run 0 V=0')
        else:
            extra=ready_conditions(name,row['ready_conditions'])
            lines.append(f'B{name}_DISABLE {name}_run 0 V=if((V({state})>.5)&({extra}),1,0)' if row['ready_conditions'] else f'B{name}_DISABLE {name}_run 0 V=V({state})')
        state=name+'_run';age=timer(name,state);fraction=name+'_fraction'
        vref=row['nominal_voltage_V'] or nominal
        if (row['mode'] in ('R','I') or any(stage['mode'] in ('R','I') for stage in row['stages'])) and vref<=0:raise ValueError(key+'需要正的负载参考电压')
        load_probes={}
        if row['stages']:
            load_probes=staged_load(lines,name,local,row,state,age,vref,probe)
            manifest['limitations'].append(key+'分阶段功耗按全部就绪条件连续满足后计时，各阶段为总运行需求；掉压回到待机并重新计时，实际电容电压不复位。阶段参数须由板卡资料或实测核实，未等同固件/芯片实测。')
        else:
            ramp=f'limit((V({age})-{_f(row["delay_s"])})/{_f(row["ramp_s"])},0,1)' if row['ramp_s']>0 else f'if(V({age})>={_f(row["delay_s"])},1,0)'
            lines.append(f'B{name}_RAMP {fraction} 0 V=if(V({state})>.5,{ramp},0)')
            demand=(f'max(V({local}),0)*{_f(row["power_W"]/(vref*vref))}' if row['mode']=='R' else
                    _f(row['power_W']/vref) if row['mode']=='I' else f'{_f(row["power_W"])}/max(V({local}),{_f(row["off_V"])})')
            compliance=row['off_V'] or min(1.,vref or 1.)
            standby=f'{_f(row["off_current_A"])}*limit(V({local})/{_f(compliance)},0,1)'
            lines.append(f'B{name}_LOAD {local} 0 I=if(V({local})>0,V({fraction})*({demand})+(1-V({fraction}))*({standby}),0)')
        compliance=row['off_V'] or min(1.,vref or 1.)
        if row['off_current_A']>0:manifest['limitations'].append(key+f'待机电流在0至{compliance:g}V按电压线性缩放，达到该电压后才取配置值；低压合规为工程假设。')
        if row['ready_conditions']:manifest['limitations'].append(key+'负载多轨条件是外部电压监控，不包含信号脚反灌、真实RESET上拉电源或跨电源域I/O保护路径。')
        if row['input_capacitance_F']>0:lines.append(f'C{name} {local} 0 {_f(row["input_capacitance_F"])} Rser={_f(row["input_esr_ohm"])}')
        if row['bleeder_ohm'] is not None:lines.append(f'R{name}_BLEED {local} 0 {_f(row["bleeder_ohm"])}')
        manifest['loads'][key]=dict(voltage_probe=probe(local),current_probe=current(sensor),state_probe=probe(fraction),config=copy.deepcopy(row),**load_probes)
    for n in p['loads']:add_load(n['id'],port_nodes[n['id']],cfg['loads'][n['id']],n['enabled'],ports.get(n['id'],0))
    for n in p['units']:
        for i,r in enumerate(n['rails'],1):
            key=n['id']+'/OUT'+str(i);add_load(key,port_nodes[key],cfg['rail_loads'][key],True,r['V_out'])
    for identity,node in port_nodes.items():
        lines.append(f'RLEAK_{node} {node} 0 1e9')
        manifest['ports'][identity]=dict(node=node,voltage_probe=probe(node),reference_V=ports.get(identity,0),name=identity)
    for n in p['units']:lines.append(f'RLEAK_{unit_names[n["id"]]} {safe[n["id"]]}_supply 0 1e9')
    lines.extend(source_caps)
    automatic_step=min(([1/(v*80) for v in frequencies]+unit_maxsteps) or [2e-6])
    maxstep=s['max_step_s'] or automatic_step
    if maxstep>automatic_step*(1+1e-9):raise ValueError('所选最大步长超过单元开关电路要求；请设0自动或更小值')
    if s['stop_s']/maxstep>25000000:raise ValueError('至少2500万时间步，超出当前RAW读取预算；请缩短启停试验或分段执行')
    lines += [f'.options threads={int(s["threads"])} method=gear reltol=.001 plotwinsize=0',
        f'.tran 0 {_f(s["stop_s"])} 0 {_f(maxstep)} uic',
        '.save '+' '.join(dict.fromkeys(save))]
    files['SystemNetwork.inc']=('\n'.join(lines)+'\n').encode('ascii')
    # Existing owned batch runner expects this name. Both decks use exactly
    # the same includes; the ASC is an annotated network overview, not PCB.
    files['Flyback.cir']=b'System power-tree startup and shutdown\n.include SystemNetwork.inc\n.end\n'
    files['SystemSequence.cir']=files['Flyback.cir']
    asc=['Version 4','SHEET 1 1600 1000','TEXT 24 24 Left 2 !.include SystemNetwork.inc',
         'TEXT 24 64 Left 2 ;SYSTEM STARTUP / SHUTDOWN -- COMMON RETURN 0',
         'TEXT 24 96 Left 2 ;Switching circuits are in per-unit includes. Traces use named ports.']
    for i,(kind,n) in enumerate(net.nodes(p)):
        x=40+{'bus':0,'unit':440,'junction':880,'load':1240}[kind];y=160+i*105
        asc += [f'RECTANGLE Normal {x} {y} {x+340} {y+78}',
            f'TEXT {x+12} {y+10} Left 2 ;{n["id"]} / {kind.upper()}',
            f'TEXT {x+12} {y+44} Left 2 ;'+('X'+unit_names[n['id']] if kind=='unit' else port_nodes.get(n['id'],''))]
    files['SystemSequence.asc']=('\n'.join(asc)+'\n').encode('ascii')
    manifest.update(max_step_s=maxstep,common_return='0',schematic_scope='annotated overview; included cards are authoritative',
        source_project_sha256=hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest())
    manifest['files']={k:dict(bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for k,v in files.items()}
    files['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')
    files['project.json']=(json.dumps(p,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')
    return files,manifest


def export_project(project,folder,*,cancelled=lambda:False,progress=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    files,manifest=project_files(project,cancelled=cancelled,progress=progress)
    for name,data in files.items():
        if Path(name).name!=name:raise ValueError('内部电路路径无效')
        (folder/name).write_bytes(data)
    return manifest
