"""Present the same full-RAW observations as HTML, Word and CSV.

No electrical solving or threshold decisions belong to this module.
"""
from __future__ import annotations
import base64
import csv
from html import escape
import io
from pathlib import Path

TITLE='电源树联合启停仿真报告'
SOURCE_MODES={'monitor':'仅门限比较（不动作）','cc':'恒流限幅','foldback':'输出电压相关折返','hiccup':'限流后打嗝重试'}


def _n(value,scale=1):
    return '未提供' if value is None else format(float(value)*scale,'.5g')


def _yes(value):
    return '已观察到' if value is True else '本次未观察到' if value is False else '未知'


def findings(result):
    messages=[]
    for row in result.get('summary',{}).get('sources',[]):
        if row.get('current_limit_exceeded'):
            mode='仅监测' if row.get('protection_mode','monitor')=='monitor' else '源保护模型'
            messages.append(row['id']+' 供流峰值 '+_n(row['supply_current_peak_A'])+' A，超过门限 '+_n(row['current_limit_A'])+' A（'+mode+'）。')
        limit=row.get('limit_state',{})
        fault=row.get('fault_state',{})
        if limit.get('on_count'):
            messages.append(row['id']+' 累计限流 '+_n(limit.get('active_time_s'),1000)+' ms。')
        if fault.get('on_count'):
            messages.append(row['id']+' 打嗝 '+str(fault['on_count'])+' 次，退出休眠 '+str(fault.get('off_count'))+' 次。')
    for row in result.get('summary',{}).get('units',[]):
        if (row['enable'].get('on_count') or 0)>1:messages.append(row['id']+'观察到'+str(row['enable']['on_count'])+'次使能；需核对供电跌落及启停门限。')
        if row['ocp'].get('fault_observed'):messages.append(row['id']+' 触发 FAULT 保护。')
        if row['ocp'].get('cycle_limit',{}).get('hit'):messages.append(row['id']+' 观察到逐周期限流。')
        if row['ocp'].get('kind')=='cot_phase_current':
            if not row['ocp'].get('observations_complete'):
                messages.append(row['id']+' COT 逐相采样或限流探针未完整覆盖。')
            if not row['ocp'].get('limit_configured'):
                messages.append(row['id']+' 未配置 COT 每相限流门限。')
            ovp=(row['ocp'].get('controller_states') or {}).get('ovp',{})
            if ovp.get('on_count'):messages.append(row['id']+' 观察到 OVP '+str(ovp['on_count'])+' 次。')
        for output in row['outputs']:
            if result.get('simulation_complete') and output.get('first_90pct_s') is None:messages.append(row['id']+'/OUT'+str(output['id'])+'在本次观察窗口未达到参考电压90%。')
            if output.get('shutdown_observation_s') is not None and output.get('decay_10pct_s') is None:
                messages.append(row['id']+'/OUT'+str(output['id'])+' 在观察结束时仍有 '+_n(output.get('residual_V'))+' V，放电未达 10% 阈值。')
    for row in result.get('summary',{}).get('loads',[]):
        stages=row.get('stage_observations',{})
        if stages.get('restart_count'):
            messages.append(row['id']+' 重新执行负载阶段 '+str(stages['restart_count'])+' 次。')
    if result.get('log_warnings'):messages.append('求解器警告 '+str(len(result['log_warnings']))+' 条，见 Flyback.log。')
    return messages


def sections(manifest,result):
    """A single presentation projection for every report format."""
    cfg=manifest.get('configuration',{});summary=result.get('summary',{})
    yield '1 试验条件与模型范围', ['项目','配置'], [
        ['运行状态',result.get('status','failed')],
        ['输入工况',manifest.get('settings',{}).get('vin_case','min')],
        ['要求 / 实际结束时间 ms',_n(manifest.get('settings',{}).get('stop_s'),1000)+' / '+_n(result.get('observed_end_s'),1000)],
        ['最大时间步 ns',_n(manifest.get('max_step_s'),1e9)],
        ['输入快照 SHA256',manifest.get('source_project_sha256','未提供')],
        ['证据范围','开关级瞬态仿真'],
        *[['未完成原因',v] for v in result.get('failure_reasons',[])],
        ['求解器警告',str(len(result.get('log_warnings',[])))+' 条，见 Flyback.log。']]
    model_rows=[];scoped_notes={}
    for identity,unit in manifest.get('units',{}).items():
        compiled=unit.get('compiled_manifest',{})
        if compiled.get('model_version'):
            model_rows.append([identity,'冻结模型版本：'+str(compiled['model_version'])])
        for note in compiled.get('approximation_notes',[]):
            if not isinstance(note,str) or not note.strip():continue
            identities=scoped_notes.setdefault(note,[])
            if identity not in identities:identities.append(identity)
    model_rows.extend(['、'.join(identities),note] for note,identities in scoped_notes.items())
    if model_rows:
        yield '1.1 冻结单元模型与近似',['适用单元','模型说明'],model_rows
    rows=[]
    for identity,row in manifest.get('sources',{}).items():
        c=row['config'];explicit=bool(c.get('voltage_profile'))
        rows.append([identity,row.get('name',''),'显式时序' if explicit else _n(c['rise_s'],1000),
                     '见下表' if explicit else _n(c['off_s'],1000),_n(c['resistance_ohm'],1000),
                     _n(c['current_limit_A']),'允许' if c.get('sink_current',False) else '阻断近似'])
    yield '2 外部输入源', ['源','名称','上升 ms','掉电 ms','源阻 mΩ','电流门限 A','反向吸流'],rows
    for index,(identity,row) in enumerate(manifest.get('sources',{}).items(),1):
        c=row['config'];mode=c.get('protection_mode','monitor');profile=c.get('voltage_profile',[])
        if mode=='monitor' and not profile and not c.get('output_capacitance_F',0):continue
        rows=[['保护模式',SOURCE_MODES.get(mode,mode)],
              ['限流门限 A',_n(c.get('current_limit_A'))],
              ['折返短路电流 A',_n(c.get('foldback_short_A')) if mode=='foldback' else '不适用'],
              ['持续限流判故障 / 休眠后重试 ms',(_n(c.get('trip_delay_s'),1000)+' / '+_n(c.get('retry_s'),1000)) if mode=='hiccup' else '不适用'],
              ['源端输出电容 / ESR',_n(c.get('output_capacitance_F',0),1e6)+' µF / '+_n(c.get('output_esr_ohm',0),1000)+' mΩ'],
              ['电流测量位置',('内部电流在限流器供能侧；源端口电流由完整RAW的 −I(内部源)−I(源端电容) 按KCL组合派生，未额外串联测量元件。' if row.get('port_current_derivation')=='source-minus-capacitor' and not row.get('port_current_probe') else '内部电流在限流器供能侧；源端口电流在输出电容后由独立探针测得。')+'电容放电可短时提供额外端口电流，休眠不强制清除残压。' if c.get('output_capacitance_F',0)>0 else '未声明源端储能电容；旧工程端口电流回退内部供流探针。'],
              ['模型依据','按设定参数计算的源保护行为模型。']]
        if profile:
            rows.append(['电压时序','显式节点取代单次上升/下降；节点之间线性插值，末值保持。'])
            rows.extend([['节点 '+str(i)+'：时间 ms / Vin倍率',_n(p['time_s'],1000)+' / '+_n(p['level'])] for i,p in enumerate(profile,1)])
        yield '2.'+str(index)+' '+identity+' 实际源行为与重复上电',['项目','配置'],rows
    rows=[]
    for identity,row in manifest.get('units',{}).items():
        c=row['config'];t=row['compiled_manifest']['sequence_unit']['thresholds']
        pg_v=c.get('pg_threshold_V')
        pg_off=None if pg_v is None else pg_v-c.get('pg_hysteresis_V',0)
        rows.append([identity,row['compiled_manifest'].get('topology',''),_n(c['vin_on_V'])+' / '+_n(c['vin_off_V']),
            _n(c['enable_s'],1000)+' / '+_n(c['disable_s'],1000),
            _n(c['soft_start_s'] if c['soft_start_s'] is not None else t.get('soft_start_s'),1000),
            ((c['wait_for_port']+'；'+_n(pg_v)+'/'+_n(pg_off)+'V；'+_n(c.get('pg_delay_s'),1000)+'ms') if c.get('wait_for_port') else '无')+
            ('；AND：'+'；'.join(x['port']+' '+_n(x['on_V'])+'/'+_n(x['off_V'])+'V' for x in c.get('ready_conditions',[])) if c.get('ready_conditions') else '')])
    yield '3 各电源启动条件', ['单元','类型','UVLO开 / 关 V','EN开 / 关 ms','软启动 ms','PG端口与开关门限及延迟'],rows
    rows=[]
    for row in summary.get('units',[]):
        enable=row['enable']
        for o in row['outputs']:
            rows.append([row['id']+'/OUT'+str(o['id']),_n(enable['first_on_s'],1000),_n(o['first_90pct_s'],1000),
                str(enable['on_count']),_n(o['voltage_peak_V']),_n(o['voltage_final_V'])])
    yield '4 启动时序与输出电压', ['输出','首次EN ms','首次90% ms','使能次数','全程峰值 V','末端 V'],rows
    rows=[]
    for row in summary.get('sources',[]):
        rows.append([row['id'],_n(row['supply_current_peak_A']),_n(row['supply_current_peak_s'],1000),
            _n(row['reverse_current_peak_A']),_n(row.get('current_limit_A')),_yes(row.get('current_limit_exceeded'))])
    yield '5 源浪涌与反向电流', ['源','限流器供流峰 A','峰值时刻 ms','内部反向峰 A','内部门限 A','内部超门限观察'],rows
    if any(row.get('separate_port_current_probe') or row.get('output_capacitance_F',0)>0 for row in summary.get('sources',[])):
        yield '5.0 源端口电流与输出储能',['源','源端口供流峰 A','峰值时刻 ms','端口反向峰 A','电容 µF / ESR mΩ'],[
            [row['id'],_n(row.get('port_supply_current_peak_A')),_n(row.get('port_supply_current_peak_s'),1000),
             _n(row.get('port_reverse_current_peak_A')),_n(row.get('output_capacitance_F',0),1e6)+' / '+_n(row.get('output_esr_ohm',0),1000)]
            for row in summary.get('sources',[])]
    rows=[]
    for row in summary.get('connections',[]):
        rows.append([row['id'],row['source']+' → '+row['target'],_n(row['current_peak_A']),_n(row['reverse_current_peak_A']),
            _n(row['first_forward_s'],1000)+' / '+_n(row['last_forward_s'],1000)])
    yield '5.1 供电支路与OR汇流', ['连接','端口关系','正向峰 A','反向峰 A','首次 / 最后供流 ms'],rows
    protected=[row for row in summary.get('sources',[]) if row.get('protection_mode','monitor')!='monitor']
    if protected:
        rows=[]
        for row in protected:
            limit=row.get('limit_state',{});fault=row.get('fault_state',{})
            rows.append([row['id'],SOURCE_MODES.get(row.get('protection_mode'),row.get('protection_mode')),
                _n(limit.get('first_on_s'),1000),_n(limit.get('active_time_s'),1000),
                _n(fault.get('on_count'))+' / '+_n(fault.get('off_count')),
                '探针齐全' if row.get('protection_observations_complete') else '探针待补充'])
        yield '5.2 源限流与保护实际动作',['源','模型','首次限流 ms','累计限流 ms','故障进入 / 退出次数','观测数据'],rows
    for unit_index,row in enumerate(summary.get('units',[]),1):
        c=row['ocp'];hit=c.get('cycle_limit',{})
        if row['topology']=='LDO':
            ldo_cfg=manifest.get('units',{}).get(row['id'],{}).get('config',{})
            yield '6.'+str(unit_index)+' '+row['id']+' 线性稳压器观察',['指标','完整RAW观察'],[
                ['输入端全程峰值 A',_n(row['input_current_peak_A'])],
                ['配置的恒定输出限流近似 A',_n(ldo_cfg.get('ldo_output_current_limit_A'))],
                ['配置的线性软启动参考 ms',_n(ldo_cfg.get('soft_start_s'),1000)],
                ['保护评估','LDO 压差和限流行为估算。']]
            continue
        if c.get('kind')=='cot_phase_current':
            states=c.get('controller_states') or {}
            yield '6.'+str(unit_index)+' '+row['id']+' COT 电流与保护观察',['指标','完整 RAW 观察'],[
                ['输入端全程峰值 A',_n(row['input_current_peak_A'])],
                ['每相采样限流门限 A',_n(c.get('phase_current_limit_A'))],
                ['逐相限流动作合计',str(hit.get('observed_phase_event_count',0))+' 次；'+_yes(hit.get('hit'))],
                ['FAULT 保护状态',_yes(c['fault_observed'])],
                ['内部 UVLO 就绪 / RUN 建立 ms',_n(states.get('uvlo',{}).get('first_on_s'),1000)+' / '+_n(states.get('run',{}).get('first_on_s'),1000)],
                ['OVP 次数 / 首次时刻 ms',_n(states.get('ovp',{}).get('on_count'))+' / '+_n(states.get('ovp',{}).get('first_on_s'),1000)],
                ['探针覆盖','完整' if c.get('observations_complete') else '未完整覆盖'],
                ['采样定义',c['sense_definition']]]
            yield '6.'+str(unit_index)+'.1 '+row['id']+' 各相电流与限流余量',[
                '相','全程峰 / 谷 A','采样峰 A','门限 A','余量 A','限流次数','首次限流 ms'],[
                [r['phase'],_n(r['current_peak_A'])+' / '+_n(r['current_min_A']),_n(r['sampled_peak_A']),
                 _n(r['threshold_A']),_n(r['sample_margin_A']),_n(r['limit_events']['on_count']),
                 _n(r['limit_events']['first_on_s'],1000)] for r in c['phases']]
            continue
        rows=[['输入端全程峰值 A',_n(row['input_current_peak_A'])],
              ['原始 / 滤波 CS峰值 V',_n(c['raw_cs_peak_V'])+' / '+_n(c['filtered_cs_peak_V'])],
              ['实际采样电阻 Ω',_n(c['sense_resistor_ohm'])],
              ['CS / Rs 等效采样支路峰值 A',_n(c['equivalent_sense_current_peak_A'])],
              ['逐周期限流正向证据',_yes(hit.get('hit'))+'；采样周期下界 '+str(hit.get('observed_cycle_count',0))],
              ['FAULT保护状态',_yes(c['fault_observed'])],
              ['保护评估','逐周期限流见采样证据，FAULT 见状态探针。']]
        for branch,values in row.get('branch_current_peaks',{}).items():
            if branch in ('LP','L1') and 'primary' in row['branch_current_peaks']:continue
            rows.append([branch+' 实际支路峰值 A',_n(values['peak_A'])])
        yield '6.'+str(unit_index)+' '+row['id']+' 电流与保护观察',['指标','完整RAW观察'],rows
    rows=[]
    for row in summary.get('loads',[]):
        c=manifest['loads'][row['id']]['config'];rows.append([row['id'],row['mode'],_n(c['on_V'])+' / '+_n(c['off_V']),
            _n(row['first_power_s'],1000)+' / '+_n(row['state'].get('first_on_s'),1000),_n(row['current_peak_A']),str(row['state']['on_count'])])
    yield '7 负载耗功与重复启动', ['负载','模型','耗功开 / 关 V','端口耗功 / 运行建立 ms','电流峰 A','启用次数'],rows
    for index,row in enumerate(summary.get('loads',[]),1):
        config=manifest.get('loads',{}).get(row['id'],{}).get('config',{})
        observations=row.get('stage_observations',{});plan=config.get('stages',[])
        if not plan:continue
        conditions='；'.join(c['port']+' ≥ '+_n(c['on_V'])+'V释放 / ≤ '+_n(c['off_V'])+'V复位' for c in config.get('ready_conditions',[]))
        details=[['本地启动 / 复位电压 V',_n(config.get('on_V'))+' / '+_n(config.get('off_V'))],
            ['额外多轨就绪条件',conditions or '无；仅用本地门限'],
            ['连续就绪后的复位释放等待 ms',_n(config.get('delay_s'),1000)],
            ['未运行时的待机电流 A',_n(config.get('off_current_A'))],
            ['实际阶段复位 / 重启次数',_n(observations.get('reset_count'))+' / '+_n(observations.get('restart_count'))],
            ['全端口 / 运行部分峰值电流 A',_n(row.get('current_peak_A'))+' / '+_n(row.get('active_current_peak_A'))],
            ['电流口径','端口含电容充电、待机、运行与泄放；运行探针只统计状态控制的运行耗流，两者峰值不一定发生于同一时刻。'],
            ['阶段口径','各阶段是总运行功耗，非增量；相对时间从本地及全部依赖连续就绪、复位等待完成后开始。掉压复位计时，电容不清零。']]
        yield '7.'+str(index)+' '+row['id']+' 复位与真实负载条件',['项目','配置 / 观察'],details
        actual={s['index']:s for s in observations.get('stages',[])}
        stage_rows=[]
        for k,stage in enumerate(plan,1):
            measured=actual.get(k,{})
            stage_rows.append([str(k)+' · '+stage['name'],stage['mode']+' / '+_n(stage['power_W']),
                _n(stage['after_s'],1000)+' / '+_n(stage['ramp_s'],1000),
                _n(measured.get('first_entry_s'),1000)+' / '+_n(measured.get('last_entry_s'),1000),
                _n(measured.get('entry_count'))])
        yield '7.'+str(index)+'.1 阶段计划与实际进入',['阶段','模式 / 总功耗 W','释放后等待 / 爬升 ms','首次 / 末次进入 ms','进入次数'],stage_rows
    rows=[]
    for row in summary.get('units',[]):
        for o in row['outputs']:
            decay=(_n(o.get('decay_10pct_s'),1000) if o.get('decay_10pct_s') is not None else
                   '本窗未降至10%' if result.get('simulation_complete') and o.get('shutdown_observation_s') is not None else '未提供')
            rows.append([row['id']+'/OUT'+str(o['id']),_n(row['enable']['last_off_s'],1000),_n(o.get('voltage_at_disable_V')),
                decay,_n(o.get('residual_V')),_n(o.get('shutdown_observation_s'),1000)])
    yield '8 关机与残余电压', ['输出','末次EN关 ms','关断时 V','低于10% ms','试验末端残压 V','观察长度 ms'],rows


def source_port_plot(identity, row, waves):
    """Display-only combination; all reported peaks come from full RAW analysis."""
    if row.get('port_current_probe'):
        return row['port_current_probe'], identity+' 端口供流', 1
    if row.get('port_current_derivation') == 'source-minus-capacitor':
        source=waves.get(row.get('current_probe','').casefold())
        cap=waves.get(row.get('output_capacitor_current_probe','').casefold())
        key=('derived:source_port:'+identity).casefold()
        if source is not None and cap is not None and len(source)==len(cap):
            waves[key]=[-float(a)-float(b) for a,b in zip(source,cap)]
        return key, identity+' 端口供流（探针组合）', 1
    return row['current_probe'], identity+' 端口供流', -1


def figures(manifest,result,folder):
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np
    waves=dict(result.get('waveforms',{}));t=waves.get('time',[])
    if len(t)<2:return []
    axis=np.asarray(t)*1000;images=[]
    colors=['#2166ba','#13a0a5','#d18524','#9660b1','#c74757','#2b8752']
    project_path=folder/'project.json'
    if project_path.is_file():
        import json
        from matplotlib.patches import FancyBboxPatch,FancyArrowPatch
        project=json.loads(project_path.read_text('utf8'))
        from power_network import nodes
        items=nodes(project);positions=project.get('layout',{}).get('nodes',{})
        xy={n['id']:(float(positions.get(kind+':'+n['id'],{}).get('x',i*360)),float(positions.get(kind+':'+n['id'],{}).get('y',0))) for i,(kind,n) in enumerate(items)}
        if len(xy)<=24:
            fig=Figure(figsize=(11.5,3.5),dpi=180);FigureCanvasAgg(fig)
            with matplotlib.rc_context({'font.family':'Microsoft YaHei','font.size':8}):
                ax=fig.add_subplot(111);ax.set_axis_off()
                for e in project.get('connections',[]):
                    sx,sy=xy[e['source']['id']];tx,ty=xy[e['target']]
                    ax.add_patch(FancyArrowPatch((sx+275,sy+56),(tx-5,ty+56),arrowstyle='-|>',mutation_scale=9,color='#98a9c0',linewidth=1.,connectionstyle='arc3,rad=.03',zorder=1))
                for kind,n in items:
                    x,y=xy[n['id']];dark=kind=='bus';edge='#0da2a9' if kind=='junction' else '#377ac9'
                    ax.add_patch(FancyBboxPatch((x,y),270,112,boxstyle='round,pad=5,rounding_size=9',facecolor='#14283f' if dark else '#f5f8fd',edgecolor=edge,linewidth=1.2,zorder=2))
                    # Names are labels, not a source of geometry: wrap CJK text
                    # within the card rather than letting long names overlap edges.
                    import re,unicodedata
                    lines=[];line='';width=0
                    tokens=re.findall(r'[A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)*|.',str(n['name']))
                    for character in tokens:
                        advance=sum(2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in character)
                        if line and width+advance>18:
                            lines.append(line);line='';width=0
                        line+=character;width+=advance
                    if line:lines.append(line)
                    if len(lines)>2:lines=lines[:1]+[lines[1][:-1]+'…']
                    label=n['id']+'\n'+'\n'.join(lines)
                    if kind=='unit':label+='\n'+n['spec']['topology']
                    elif kind=='bus':label+='\n'+_n(n['min'])+' V'
                    elif kind=='load':label+='\n'+_n(n['power'])+' W'
                    ax.text(x+135,y+56,label,ha='center',va='center',color='white' if dark else '#17365d',fontsize=9,zorder=3)
                ax.set_xlim(min(x for x,y in xy.values())-30,max(x for x,y in xy.values())+300)
                ax.set_ylim(max(y for x,y in xy.values())+140,min(y for x,y in xy.values())-40)
                ax.set_title('本次冻结的电源树连接  公共返回 0',fontsize=12,pad=12)
                fig.tight_layout(pad=.8);path=folder/'architecture.png';fig.savefig(path,facecolor='white');images.append(('电源树连接与节点',path))
    def add(title,traces,ylabel,filename):
        if not traces:return
        fig=Figure(figsize=(10.3,3.5),dpi=160);FigureCanvasAgg(fig)
        with matplotlib.rc_context({'font.family':'Microsoft YaHei','font.size':10}):
            ax=fig.add_subplot(111)
            for i,(probe,label,scale) in enumerate(traces):
                values=waves.get(probe.casefold())
                if values is not None:ax.plot(axis,np.asarray(values)*scale,label=label,color=colors[i%len(colors)],linewidth=1.25)
            ax.set(xlabel='时间 / ms',ylabel=ylabel,title=title)
            ax.grid(color='#dfe6ef',linewidth=.6);ax.legend(loc='upper right',fontsize=8,ncol=min(3,len(traces)))
            fig.tight_layout(pad=1.3);path=folder/filename;fig.savefig(path,facecolor='white')
        images.append((title,path))
    src=manifest.get('sources',{});units=manifest.get('units',{})
    add('外部源与各级输出电压',[(v['voltage_probe'],k,1) for k,v in src.items()]+[(o['voltage_probe'],k+'/OUT'+str(o['id']),1) for k,u in units.items() for o in u['outputs']], 'V','voltages.png')
    add('外部源限流器供流与主备切换',[(v['current_probe'],k+' 内部供流',-1) for k,v in src.items()], 'A','sources.png')
    if any(v.get('port_current_probe') or v.get('port_current_derivation') for v in src.values()):
        add('外部源端口供流 含输出电容放电',[source_port_plot(k,v,waves) for k,v in src.items()], 'A','source-ports.png')
    branch=[(v['current_probe'],k+' '+v['source'],1) for k,v in manifest.get('connections',{}).items()
            if any(other['target']==v['target'] and other is not v for other in manifest.get('connections',{}).values())]
    add('OR汇流支路电流 按瞬时电压与阻抗竞争',branch,'A','oring.png')
    add('各电源输入电流 包含输入电容充电',[(u['input_current_probe'],k,1) for k,u in units.items()], 'A','inputs.png')
    add('使能与负载耗功状态',[(u['en_probe'],k+' EN',1) for k,u in units.items()]+[(u['state_probe'],k+' 耗功',1) for k,u in manifest.get('loads',{}).items()], '状态','enables.png')
    def panels(title, rows, filename):
        """Separate units/logic axes to keep current and state scales legible."""
        fig=Figure(figsize=(10.3,5.7),dpi=160);FigureCanvasAgg(fig)
        with matplotlib.rc_context({'font.family':'Microsoft YaHei','font.size':9}):
            for index,(ylabel,traces,thresholds) in enumerate(rows,1):
                ax=fig.add_subplot(len(rows),1,index)
                plotted=False
                for i,(probe,label,scale) in enumerate(traces):
                    if not isinstance(probe,str):continue
                    values=waves.get(probe.casefold())
                    if values is not None:
                        ax.plot(axis,np.asarray(values)*scale,label=label,color=colors[i%len(colors)],linewidth=1.2)
                        plotted=True
                for value,label in thresholds:
                    if value is not None:ax.axhline(value,color='#c74757',linestyle='--',linewidth=.9,label=label);plotted=True
                ax.set(ylabel=ylabel)
                ax.grid(color='#dfe6ef',linewidth=.6)
                if plotted:ax.legend(loc='upper right',fontsize=8,ncol=2)
                if index==1:ax.set_title(title,pad=10)
                if index==len(rows):ax.set_xlabel('时间 / ms')
            fig.tight_layout(pad=1.3)
            path=folder/filename;fig.savefig(path,facecolor='white')
        images.append((title,path))
    for index,(k,v) in enumerate(src.items(),1):
        if v.get('config',{}).get('protection_mode','monitor')=='monitor':continue
        panels(k+' 源输出与实际保护状态',[
            ('V',[(v.get('voltage_probe'),'端口电压',1)],[]),
            ('A',[(v.get('current_probe'),'限流器内部供流',-1)]+([source_port_plot(k,v,waves)] if v.get('port_current_probe') or v.get('port_current_derivation') else []),[(v.get('config',{}).get('current_limit_A'),'内部限流门限')]),
            ('状态',[(v.get('limit_active_probe'),'限流有效',1),(v.get('fault_probe'),'故障 / 休眠',1)],[])],
            f'source-{index}-protection.png')
    for index,(k,v) in enumerate(manifest.get('loads',{}).items(),1):
        if not v.get('config',{}).get('stages'):continue
        panels(k+' 分阶段负载、复位与实际耗流',[
            ('V',[(v.get('voltage_probe'),'负载端电压',1)],[]),
            ('A',[(v.get('current_probe'),'端口总电流',1),(v.get('active_current_probe'),'运行部分电流',1)],[]),
            ('阶段 / 状态',[(v.get('stage_probe'),'阶段编号（0=复位等待）',1),(v.get('ready_probe'),'全部条件就绪',1)],[])],
            f'load-{index}-stages.png')
    for k,u in units.items():
        controller=u['probes'].get('controller',{})
        if u['probes'].get('cot_phase_limits'):
            current=u['probes'].get('currents',{})
            phase_list=list(u['probes']['cot_phase_limits'])
            for offset in range(0,len(phase_list),4):
                group=phase_list[offset:offset+4]
                panels(k+' COT 各相电流与限流状态',[
                    ('A',[(current.get('L'+name[5:]),'PH'+name[5:],1) for name in group],[]),
                    ('状态',[(u['probes']['cot_phase_limits'][name],'PH'+name[5:]+' 限流',1) for name in group],[])],
                    k+'-cot-'+str(offset//4+1)+'.png')
            continue
        add(k+' 电流采样与保护',[(u['probes'][name],name,1) for name in ('sense','fault') if name in u['probes']]+
            [(controller[name],name,1) for name in ('filtered_cs','cycle_limit') if name in controller], 'V',k+'-cs.png')
    return images


def write(folder,manifest,result,*,word=True,plots=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    blocks=list(sections(manifest,result));plots=figures(manifest,result,folder) if plots is None else plots
    limits=list(dict.fromkeys(manifest.get('limitations',[])+result.get('limitations',[])))
    failures=result.get('failure_reasons',[]);notes=findings(result)
    status={'completed':'仿真已完成','failed':'仿真未完成','cancelled':'仿真已取消'}.get(result.get('status'),'仿真状态待确认')
    outputs=[output for unit in result.get('summary',{}).get('units',[]) for output in unit.get('outputs',[])]
    if result.get('simulation_complete') and outputs:
        reached=sum(output.get('first_90pct_s') is not None for output in outputs)
        status+=f'。{reached}/{len(outputs)} 路输出达到参考电压的 90%'
    sampling='表内峰值、事件和计数直接统计完整RAW。波形图最多显示 2400 点。'
    body=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">',
        '<title>'+TITLE+'</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;background:#f3f6fb;color:#1c2a3c;margin:0}main{max-width:1180px;margin:36px auto;background:white;padding:38px;border-radius:16px}h1{font-size:30px;color:#17365d}h2{font-size:22px;color:#17365d;margin-top:34px}table{border-collapse:collapse;width:100%;font-size:14px;margin:16px 0}th,td{border:1px solid #d9e1ec;padding:10px;text-align:left;overflow-wrap:anywhere}th{background:#17365d;color:white}tr:nth-child(even){background:#f1f5fb}img{max-width:100%;display:block;margin:20px auto}p{margin:12px 0}.failure{color:#ac2236;font-weight:bold}@media print{main{margin:0;padding:0}body{background:white}h2{break-after:avoid}tr,img{break-inside:avoid}}</style><main>',
        '<h1>'+TITLE+'</h1><h2>关键结论</h2><p><strong>'+escape(status)+'。</strong></p>']
    for p in failures:body.append('<p class="failure">'+escape(p)+'</p>')
    for p in notes:body.append('<p class="failure">'+escape(p)+'</p>')
    for title,headers,rows in blocks:
        body += ['<h2>'+escape(title)+'</h2>','<table><thead><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>']
        body += ['<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows]
        body.append('</tbody></table>')
    body.append('<h2>9 实际波形</h2>')
    for title,path in plots:
        data=base64.b64encode(path.read_bytes()).decode('ascii');body.append('<img alt="'+escape(title)+'" src="data:image/png;base64,'+data+'">')
    body.append('<h2>10 原始数据与模型范围</h2><p>'+escape(sampling)+' 完整事件见 events.csv。</p>')
    body += ['<p>'+escape(p)+'</p>' for p in limits]
    body.append('</main></html>');html=folder/(TITLE+'.html');html.write_text('\n'.join(body),encoding='utf8')
    with (folder/'events.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['time_ms','node_id','event','details'])
        for e in result.get('events',[]):writer.writerow([_n(e['time_s'],1000),e['id'],e['type'],str({k:v for k,v in e.items() if k not in ('time_s','id','type')})])
    with (folder/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        for title,headers,rows in blocks:writer.writerow([title]);writer.writerow(headers);writer.writerows(rows);writer.writerow([])
    document=None
    if word:
        from docx_layout import new_document,paragraph,table,figure,finalize_book_report
        from docx.shared import Pt
        doc=new_document(TITLE,'开关级联合瞬态  启动时序  输入浪涌  主备切换  关机残压','电源树联合启停')
        from docx_layout import _font
        doc.add_heading('关键结论', level=1)
        paragraph(doc,status+'。').runs[0].bold=True
        for p in failures+notes:
            observed=paragraph(doc,p)
            for run in observed.runs:_font(run,11,bold=True,color='A32436')
        for title,headers,rows in blocks:
            doc.add_heading(title.split(' ', 1)[1], level=1)
            if rows:
                block=table(doc,headers,rows)
                # Keep compact engineering tables together. LibreOffice can
                # omit continuation rows when a page begins with a new table.
                # Longer user-generated connection lists still flow normally.
                if len(rows)<=12 and sum(len(str(value)) for row in rows for value in row)<3000:
                    for row in block.rows[:-1]:
                        for cell in row.cells:
                            for p in cell.paragraphs:p.paragraph_format.keep_with_next=True
            else:paragraph(doc,'本次无记录。')
        doc.add_heading('实际波形',level=1)
        for title,path in plots:figure(doc,path.read_bytes(),title,width=7.1)
        doc.add_heading('原始数据与模型范围',level=1)
        paragraph(doc,sampling+' 完整事件见 events.csv。')
        for p in limits:paragraph(doc,p)
        for p in doc.paragraphs:
            if p.style.name=='Normal':p.paragraph_format.space_after=Pt(6)
        finalize_book_report(doc)
        document=folder/(TITLE+'.docx');doc.save(document)
    return dict(report_path=str(document or html),html_path=str(html),word_path=str(document) if document else None,
                csv_path=str(folder/'summary.csv'),images=[str(p) for _,p in plots])
