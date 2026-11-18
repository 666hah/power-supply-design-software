"""SI configuration for system-level switching transient experiments.

No converter calculation or Tk access. Unknown startup/OCP thresholds remain
None; engineering impedance defaults are assumptions, never measured values.
"""
from __future__ import annotations
import copy
import math

SCHEMA='power.system-sequence/1'


def nominal_ports(project,case='min'):
    import power_network as net
    result={}
    for identity in net.topological_order(project):
        kind,node=next((k,n) for k,n in net.nodes(project) if n['id']==identity)
        if kind=='bus':result[identity]=float(node[case])
        elif kind=='unit':
            for i,rail in enumerate(node['rails'],1):result[f'{identity}/OUT{i}']=float(rail['V_out'])
        else:
            values=[result.get(net.port_key(e['source']),0)-(e['vf'] if e['mode']=='diode' else 0)
                    for e in net.incoming(project,identity) if e['enabled']]
            result[identity]=max([0.,*values])
    return result


def _load(power,voltage,enabled=True):
    return dict(enabled=enabled,mode='R',power_W=float(power),nominal_voltage_V=float(voltage),
        on_V=None,off_V=None,delay_s=0.,ramp_s=.001,off_current_A=0.,
        input_capacitance_F=0.,input_esr_ohm=.1,bleeder_ohm=None,stages=[],ready_conditions=[])


def defaults(project):
    ports=nominal_ports(project)
    cfg=dict(schema=SCHEMA,settings=dict(stop_s=.04,timeout_s=600.,threads=2,vin_case='min',max_step_s=0.,include_switching_capacitance=True),
        sources={},units={},loads={},rail_loads={},connections={})
    for n in project['sources']:
        cfg['sources'][n['id']]=dict(on_s=0.,rise_s=.002,off_s=.025,fall_s=.002,
            resistance_ohm=.05,inductance_H=0.,output_capacitance_F=0.,output_esr_ohm=.1,
            current_limit_A=None,sink_current=False,protection_mode='monitor',foldback_short_A=None,trip_delay_s=.001,retry_s=.01,voltage_profile=[])
    for n in project['units']:
        cfg['units'][n['id']]=dict(enable_s=0.,disable_s=.035,vin_on_V=None,vin_off_V=None,
            soft_start_s=None,vcc_mode='ideal',wait_for_port='',pg_threshold_V=None,pg_delay_s=0.,pg_hysteresis_V=0.,
            ldo_output_current_limit_A=None,ldo_output_resistance_ohm=.1,ready_conditions=[])
        for i,r in enumerate(n['rails'],1):
            port=f'{n["id"]}/OUT{i}'
            # Any declared outgoing link suppresses the standalone rated
            # fixture, even when the downstream node/link is currently off.
            linked=any(e['source']['kind']=='unit' and e['source']['id']==n['id'] and e['source']['output']==i for e in project['connections'])
            cfg['rail_loads'][port]=_load(r['P_out'],r['V_out'],not linked)
    for n in project['loads']:cfg['loads'][n['id']]=_load(n['power'],ports.get(n['id'],0.))
    for e in project['connections']:cfg['connections'][e['id']]=dict(resistance_ohm=.01,inductance_H=0.)
    return cfg


def normalize(project,value=None):
    base=defaults(project)
    value=project.get('sequence_config',{}) if value is None else value
    if not isinstance(value,dict):raise ValueError('联合启停设置必须为对象')
    if value.get('schema',SCHEMA)!=SCHEMA:raise ValueError('联合启停设置版本不支持')
    if set(value)-set(base):raise ValueError('联合启停设置含未知分组')
    def merge(target,raw,label):
        if not isinstance(raw,dict) or set(raw)-set(target):raise ValueError(label+'含未知字段或不是对象')
        target.update(copy.deepcopy(raw));return target
    merge(base['settings'],value.get('settings',{}),'运行设置')
    for group in ('sources','units','loads','rail_loads','connections'):
        rows=value.get(group,{})
        if not isinstance(rows,dict):raise ValueError(group+'必须按稳定ID保存')
        # Preserve settings for deleted nodes as inactive drafts. They are
        # never used by the exporter until a matching node exists again.
        template=next(iter(base[group].values()),None)
        if template is None:
            template=(_load(0,0) if group in ('loads','rail_loads') else
                dict(resistance_ohm=.01,inductance_H=0.) if group=='connections' else
                dict(on_s=0.,rise_s=.002,off_s=.025,fall_s=.002,resistance_ohm=.05,inductance_H=0.,output_capacitance_F=0.,output_esr_ohm=.1,current_limit_A=None,sink_current=False,protection_mode='monitor',foldback_short_A=None,trip_delay_s=.001,retry_s=.01,voltage_profile=[]) if group=='sources' else
                dict(enable_s=0.,disable_s=.035,vin_on_V=None,vin_off_V=None,soft_start_s=None,vcc_mode='ideal',wait_for_port='',pg_threshold_V=None,pg_delay_s=0.,pg_hysteresis_V=0.,ldo_output_current_limit_A=None,ldo_output_resistance_ohm=.1,ready_conditions=[]))
        for key,row in rows.items():
            if not isinstance(key,str) or not key or len(key)>100:raise ValueError('启停配置ID无效')
            base[group][key]=merge(base[group].get(key,copy.deepcopy(template)),row,group+'/'+key)
    def number(v,label,lo=0.,hi=1e9,nullable=False):
        if nullable and v is None:return
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError(f'{label}须为{lo:g}至{hi:g}有限数值'+('，未知留空' if nullable else ''))
    s=base['settings']
    for k,lo,hi in [('stop_s',1e-5,10.),('timeout_s',10,7200),('threads',1,8),('max_step_s',0,1e-3)]:number(s[k],k,lo,hi)
    if int(s['threads'])!=s['threads']:raise ValueError('线程数须为整数')
    if s['vin_case'] not in ('min','max'):raise ValueError('请选择Vinmin或Vinmax；每次整网使用同一端点')
    if not isinstance(s['include_switching_capacitance'],bool):raise ValueError('Buck/Boost保留器件寄生电容须明确为布尔值')
    for identity,row in base['sources'].items():
        for k in ('on_s','rise_s','off_s','fall_s'):number(row[k],identity+'/'+k,0,10)
        if not row['voltage_profile'] and (row['rise_s']<=0 or row['fall_s']<=0 or row['off_s']<row['on_s']+row['rise_s']):
            raise ValueError(identity+'源上升/下降时间须大于0，关断时间不得早于升压结束')
        number(row['resistance_ohm'],identity+'/源电阻',1e-6,1e6)
        number(row['inductance_H'],identity+'/源电感',0,100)
        number(row['output_capacitance_F'],identity+'/源端输出电容',0,10.)
        # Zero ESR is an explicit ideal capacitor, not silently replaced with
        # a numerical resistance. This capacitor is outside converter Cin.
        number(row['output_esr_ohm'],identity+'/源端输出电容ESR',0,1e6)
        number(row['current_limit_A'],identity+'/源电流门限',1e-9,1e9,True)
        if not isinstance(row['sink_current'],bool):raise ValueError(identity+'反向吸流能力须明确为布尔值')
        mode=row['protection_mode']
        if mode not in ('monitor','cc','foldback','hiccup'):raise ValueError(identity+'源保护类型无效')
        number(row['foldback_short_A'],identity+'/折返短路电流',1e-9,1e9,True)
        number(row['trip_delay_s'],identity+'/连续限流触发延时',1e-6,10.)
        number(row['retry_s'],identity+'/打嗝休眠时间',1e-6,10.)
        if mode!='monitor' and row['current_limit_A'] is None:raise ValueError(identity+'实际限流必须填写源电流门限')
        if mode!='monitor' and row['inductance_H']>0:raise ValueError(identity+'主动源保护暂不支持源串联电感：需要明确续流/钳位回路；请用0或仅比较模式')
        if mode=='foldback' and (row['foldback_short_A'] is None or row['foldback_short_A']>row['current_limit_A']):raise ValueError(identity+'折返短路电流须为正且不大于源限流')
        profile=row['voltage_profile']
        if not isinstance(profile,list) or len(profile)>256:raise ValueError(identity+'输入时序须为不超过256项的列表')
        previous=-1.
        for index,point in enumerate(profile):
            if not isinstance(point,dict) or set(point)!={'time_s','level'}:raise ValueError(identity+'输入时序须含time_s和level')
            number(point['time_s'],identity+'/输入时刻',0,10.)
            number(point['level'],identity+'/输入电压倍率',0,10.)
            if point['time_s']<=previous or (index==0 and point['time_s']!=0):raise ValueError(identity+'输入时序须从0秒开始并严格递增')
            previous=point['time_s']
        if profile and len(profile)<2:raise ValueError(identity+'输入时序至少两个点')
    ports=nominal_ports(project)
    def conditions(identity,rows):
        if not isinstance(rows,list) or len(rows)>32:raise ValueError(identity+'就绪条件须为不超过32项的列表')
        seen=set()
        for condition in rows:
            if not isinstance(condition,dict) or set(condition)!={'port','on_V','off_V'}:raise ValueError(identity+'就绪条件须含port/on_V/off_V')
            port=condition['port']
            if not isinstance(port,str) or not port or len(port)>100 or port in seen:raise ValueError(identity+'就绪端口须为非空且不重复的ID')
            seen.add(port)
            number(condition['on_V'],identity+'/就绪开启电压',1e-9,1e6)
            number(condition['off_V'],identity+'/就绪关闭电压',0,1e6)
            if condition['on_V']<=condition['off_V']:raise ValueError(identity+'就绪开启电压须高于关闭电压')
    for identity,row in base['units'].items():
        for k in ('enable_s','disable_s','pg_delay_s'):number(row[k],identity+'/'+k,0,10)
        if row['disable_s']<=row['enable_s']:raise ValueError(identity+'关断时间须晚于使能时间')
        for k in ('vin_on_V','vin_off_V'):number(row[k],identity+'/'+k,0,1e6,True)
        if (row['vin_on_V'] is None)!=(row['vin_off_V'] is None):raise ValueError(identity+'输入UVLO启停门限必须同时填写或同时留空')
        if row['vin_on_V'] is not None and row['vin_on_V']<=row['vin_off_V']:raise ValueError(identity+'输入启动门限须大于关闭门限')
        number(row['soft_start_s'],identity+'/软启动',1e-6,.1,True)
        if row['vcc_mode'] not in ('ideal','enable_follow'):raise ValueError('VCC模式仅支持ideal或enable_follow')
        if not isinstance(row['wait_for_port'],str):raise ValueError('PG依赖须为端口ID')
        # Missing/deleted PG references are preserved for editing and rejected
        # by export, so deleting a canvas node cannot discard its settings.
        number(row['pg_threshold_V'],identity+'/PG门限',0,1e6,True)
        number(row['pg_hysteresis_V'],identity+'/PG迟滞',0,1e6)
        if row['wait_for_port'] and (row['pg_threshold_V'] is None or row['pg_threshold_V']<=0):raise ValueError(identity+'等待PG时须指定正的门限电压')
        if row['wait_for_port'] and row['pg_hysteresis_V']>=row['pg_threshold_V']:raise ValueError(identity+'PG迟滞须小于启动门限')
        number(row['ldo_output_current_limit_A'],identity+'/LDO明确输出限流',1e-9,1e6,True)
        number(row['ldo_output_resistance_ohm'],identity+'/LDO等效输出电阻',1e-6,1e6)
        conditions(identity,row['ready_conditions'])
    for group in ('loads','rail_loads'):
        for identity,row in base[group].items():
            if not isinstance(row['enabled'],bool) or row['mode'] not in ('R','I','P'):raise ValueError(identity+'负载启用/类型无效')
            for k in ('power_W','nominal_voltage_V','off_current_A','input_capacitance_F','input_esr_ohm','delay_s','ramp_s'):
                number(row[k],identity+'/'+k,0,1e6 if k in ('power_W','nominal_voltage_V','off_current_A') else 10)
            for k in ('on_V','off_V'):number(row[k],identity+'/'+k,0,1e6,True)
            number(row['bleeder_ohm'],identity+'/泄放电阻',1e-6,1e12,True)
            if (row['on_V'] is None)!=(row['off_V'] is None):raise ValueError(identity+'负载启停电压须同时填写或同时留空')
            if row['on_V'] is not None and row['on_V']<=row['off_V']:raise ValueError(identity+'负载启动电压须大于停止电压')
            if not isinstance(row['stages'],list):raise ValueError(identity+'负载阶段须为列表')
            # An explicit stage list replaces the legacy running demand. Keep
            # its dormant mode for switching back, but validate only modes
            # that can actually consume power in this configuration.
            demand_modes = [stage.get('mode') for stage in row['stages'] if isinstance(stage,dict)] if row['stages'] else [row['mode']]
            if any(mode in ('I','P') for mode in demand_modes) and row['enabled'] and (row['on_V'] is None or row['off_V']<=0):
                raise ValueError(identity+'恒流/恒功率负载必须有正的耗功启停电压，禁止0V时吸取额定电流/功率')
            if row['input_capacitance_F']>0 and row['input_esr_ohm']<=0:raise ValueError(identity+'附加输入电容需要正的ESR')
            conditions(identity,row['ready_conditions'])
            stages=row['stages']
            if not isinstance(stages,list) or len(stages)>32:raise ValueError(identity+'负载阶段须为不超过32项的列表')
            previous=None
            for index,stage in enumerate(stages):
                if not isinstance(stage,dict) or set(stage)!={'name','after_s','mode','power_W','ramp_s'}:raise ValueError(identity+'阶段须含name/after_s/mode/power_W/ramp_s')
                if not isinstance(stage['name'],str) or not stage['name'].strip() or len(stage['name'])>100:raise ValueError(identity+'阶段名称须非空且不超过100字')
                if stage['mode'] not in ('R','I','P'):raise ValueError(identity+'阶段类型无效')
                for k,hi in [('after_s',10.),('ramp_s',10.),('power_W',1e6)]:number(stage[k],identity+'/'+k,0,hi)
                if index==0 and stage['after_s']!=0:raise ValueError(identity+'首个负载阶段须从0开始')
                if previous is not None and (stage['after_s']<=previous['after_s'] or previous['after_s']+previous['ramp_s']>stage['after_s']):raise ValueError(identity+'负载阶段时刻须递增且爬升不得跨越下一阶段')
                previous=stage
    for identity,row in base['connections'].items():
        number(row['resistance_ohm'],identity+'/支路R',1e-6,1e6)
        number(row['inductance_H'],identity+'/支路L',0,100)
    return base
