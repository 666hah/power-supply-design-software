"""Summarize actual staged-tree evidence; never launches or fabricates a solve."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABELS = {'normal':'正常启动与主备切换', 'weak_hiccup':'弱源打嗝故障注入',
          'warm_restart':'掉电与带残压重启', 'slow_input':'缓慢输入建立'}


def number(value, scale=1):
    return '未观察到' if value is None else f'{float(value)*scale:.5g}'


def load(path):
    return json.loads(Path(path).read_text('utf8'))


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def audit_conclusions(audit_path,directories):
    """Bind conclusions to exactly these frozen runs, including complete RAW."""
    states={name:dict(bound=False,passed=None,text='未独立验收',details='未提供 --audit 参数') for name in LABELS}
    if audit_path is None:return states,None
    value=load(audit_path)
    if value.get('schema')!='power.staged-sequence-independent-evidence/1':
        raise ValueError('独立验收JSON schema不匹配，请运行check_staged_sequence_evidence.py。')
    for name in LABELS:
        row=value.get('cases',{}).get(name)
        if row is None:
            states[name]['details']='验收文件未覆盖此工况';continue
        expected=row.get('sha256',{});directory=directories[name]
        names=('project.json','manifest.json','result.json','Flyback.log','Flyback.raw')
        mismatch=[file for file in names if not expected.get(file) or not (directory/file).is_file() or digest(directory/file)!=expected[file]]
        if mismatch:
            states[name].update(text='独立验收证据不匹配',details='请重新验收：'+', '.join(mismatch));continue
        passed=row.get('scenario_expectations_met')
        if not isinstance(passed,bool):
            states[name]['details']='验收缺少明确的场景结论';continue
        fail=[c['name'] for c in row.get('checks',[]) if not c.get('passed')]
        states[name]=dict(bound=True,passed=passed,
            text=('符合故障预期' if name=='weak_hiccup' else '符合声明场景预期') if passed else '独立验收未通过',
            details='；'.join(fail[:4]) if fail else ('故障和重试符合预期，不是正常启动通过' if name=='weak_hiccup' else '完整时域、实际限流、阶段及条件已核对'))
    overall=[c for c in value.get('checks',[]) if not c.get('passed')]
    return states,dict(path=str(Path(audit_path).resolve()),sha256=digest(audit_path),
        all_selected_expectations_met=value.get('all_selected_expectations_met'),
        cross_case_failures=[c['name'] for c in overall],
        cross_case_checks=value.get('checks',[]))


def resolve_directory(folder,entry):
    if not entry.get('directory'):raise ValueError('场景尚无运行目录，不能生成完整试验总览。')
    directory=Path(entry['directory']).resolve()
    if not directory.is_dir():
        # Preserve portability without silently selecting another attempt.
        candidates=list(folder.glob('*/'+Path(entry['directory']).name))
        if len(candidates)!=1:raise ValueError('找不到该次冻结运行：'+entry['directory'])
        directory=candidates[0].resolve()
    try:directory.relative_to(folder)
    except ValueError:raise ValueError('运行目录必须位于本证据包内，避免打包无关文件：'+str(directory))
    return directory


def scenario_inputs(manifest):
    rows=[]
    for key,row in manifest.get('sources',{}).items():
        config=row['config'];profile=config.get('voltage_profile')
        text=key+' '+config.get('protection_mode','monitor')+' '+number(config.get('current_limit_A'))+'A'
        if profile:
            text+='；电压倍率序列 '+', '.join(f"{p['time_s']*1000:g}ms:{p['level']:g}" for p in profile)
        else:text+=f"；上升{config['rise_s']*1000:g}ms，{config['off_s']*1000:g}ms掉电"
        if config.get('protection_mode')=='hiccup':text+=f"；限流{config['trip_delay_s']*1000:g}ms后停{config['retry_s']*1000:g}ms"
        rows.append(text)
    return '\n'.join(rows)


def model_approximations(manifests):
    """Read the actual frozen model declarations, not a current-code claim."""
    selected=[]
    for manifest in manifests.values():
        texts=list(manifest.get('limitations',[]))
        for unit in manifest.get('units',{}).values():
            compiled=unit.get('compiled_manifest',{})
            texts.extend(compiled.get('limitations',[]))
            texts.extend(compiled.get('approximation_notes',[]))
            texts.extend(compiled.get('sequence_unit',{}).get('limitations',[]))
        for text in texts:
            if any(word in text for word in ('平滑','转折','epsilon','连续开关','连续电导','Vh=','0.1%','回零')) and text not in selected:
                selected.append(text)
    return selected


def report_references(doc,references):
    """Compact clickable primary references, without orphaned long URLs."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx_layout import paragraph
    p=paragraph(doc,'参考资料：',small=True)
    for index,(label,url) in enumerate(references):
        if index:p.add_run('； ')
        link=OxmlElement('w:hyperlink')
        link.set(qn('r:id'),p.part.relate_to(url,RELATIONSHIP_TYPE.HYPERLINK,is_external=True))
        run=OxmlElement('w:r');props=OxmlElement('w:rPr')
        color=OxmlElement('w:color');color.set(qn('w:val'),'165D9A');props.append(color)
        size=OxmlElement('w:sz');size.set(qn('w:val'),'18');props.append(size)
        underline=OxmlElement('w:u');underline.set(qn('w:val'),'single');props.append(underline)
        run.append(props);text=OxmlElement('w:t');text.text=label;run.append(text)
        link.append(run);p._p.append(link)
    return p


def report_table(doc,headers,rows,**kwargs):
    """Keep compact summary tables intact across Word/LibreOffice pages."""
    from docx_layout import table
    rows=list(rows)
    block=table(doc,headers,rows,**kwargs)
    if len(rows)<=12 and sum(len(str(value)) for row in rows for value in row)<3000:
        for row in block.rows[:-1]:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_with_next=True
    return block


def ocp_observation(ocp):
    """Keep sampled unknown, positive limit evidence and FAULT distinct."""
    cycle=ocp.get('cycle_limit',{})
    hit=cycle.get('hit')
    if hit is True:
        limit='已观测限流；周期数≥'+number(cycle.get('observed_cycle_count'))
    elif hit is False:
        limit='明确状态未命中'
    else:
        limit='未取得限流正向证据（未知）'
    fault=ocp.get('fault_observed')
    status='已观察到FAULT' if fault is True else ('未观察到FAULT' if fault is False else 'FAULT未知')
    return limit+'；'+status


def package_files(folder,directories,report_name,include_audit):
    """Select each run's original evidence once, excluding nested archives/QA."""
    root_names={'validation.json','完整分阶段电源树示例.json','README.md','package-evidence.json',report_name}
    root_names.update(name+'.json' for name in LABELS)
    if include_audit:root_names.add('独立RAW验收.json')
    selected=[folder/name for name in sorted(root_names) if (folder/name).is_file()]
    extensions={'.json','.inc','.lib','.cir','.asc','.raw','.log','.csv','.html','.docx','.png'}
    for run in directories.values():
        for path in sorted(run.rglob('*')):
            relative=path.relative_to(run)
            if any(part.lower() in {'qa','render','rendered','pages','__pycache__'} or part.lower().startswith('qa-') for part in relative.parts[:-1]):continue
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in extensions:continue
            if path.name.lower().startswith('page-') and path.suffix.lower()=='.png':continue
            selected.append(path)
    return list(dict.fromkeys(path.resolve() for path in selected))


def write_archive(folder,directories,report_name,include_audit):
    """Reuse verified identical archives; compress full RAW once at fast level."""
    files=package_files(folder,directories,report_name,include_audit)
    members=[dict(path=str(path.relative_to(folder)).replace('\\','/'),bytes=path.stat().st_size,sha256=digest(path)) for path in files]
    target=folder/'完整分阶段电源树_工程与仿真证据.zip'
    receipt_path=target.with_suffix('.zip.receipt.json')
    if receipt_path.is_file() and target.is_file():
        old=load(receipt_path)
        if old.get('members')==members and old.get('archive_sha256')==digest(target):
            return dict(path=str(target),reused=True,bytes=target.stat().st_size)
    started=time.monotonic();temporary=target.with_suffix('.zip.writing')
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for path,row in zip(files,members):
                stored=path.suffix.lower() in {'.png','.docx'}
                archive.write(path,row['path'],compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                    compresslevel=None if stored else 1)
        temporary.replace(target)
    finally:
        if temporary.exists():temporary.unlink()
    receipt=dict(schema='power.staged-sequence-archive/1',members=members,
        archive_sha256=digest(target),archive_bytes=target.stat().st_size,elapsed_s=time.monotonic()-started,
        policy='Only selected frozen runs; complete RAW once; DEFLATE level1; already-compressed DOCX/PNG stored; no nested archives or QA renders')
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return dict(path=str(target),reused=False,bytes=receipt['archive_bytes'],elapsed_s=receipt['elapsed_s'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--zip',action='store_true')
    parser.add_argument('--audit',type=Path,help='check_staged_sequence_evidence.py生成的JSON；逐工况核对完整RAW指纹')
    args = parser.parse_args(argv)
    folder = args.folder.resolve()
    receipt = load(folder/'validation.json')
    cases = receipt['cases']
    if set(LABELS)-set(cases):
        raise ValueError('四种试验没有齐全，不生成完整试验总览。')
    results, manifests, directories = {}, {}, {}
    for name in LABELS:
        directory = resolve_directory(folder,cases[name]);directories[name]=directory
        results[name] = load(directory/'result.json')
        manifests[name] = load(directory/'manifest.json')
    audit_states,audit_info=audit_conclusions(args.audit,directories)
    from docx_layout import new_document, paragraph, figure
    table=report_table
    title = '完整电源树启停与分阶段负载验证报告'
    doc = new_document(title, '同一套硬件 四种独立试验 实际 LTspice RAW 证据\n'+date.today().isoformat(), '电源树联合启停 验证总览')
    paragraph(doc, '本报告验证软件的联合启停模型及其声明的试验条件。电路确实在同一次开关级瞬态中连接，'
        '不代表已验证真实芯片全部内部逻辑或实物保护。每个工况的完整参数、波形、日志和事件表见同目录子报告。')
    bound=all(state['bound'] for state in audit_states.values())
    passed=bound and all(state['passed'] for state in audit_states.values()) and audit_info is not None and audit_info['all_selected_expectations_met'] is True
    paragraph(doc,'独立验收结论：'+('四个声明场景均符合预期；弱源工况正确进入故障和重试，不属于正常启动通过。' if passed else
        '尚未全部满足独立验收条件；下表保留未验证或失败项，不能仅凭仿真运行结束宣称设计通过。'))
    doc.add_heading('1 连接关系与负担',1)
    paragraph(doc, '24V 主源 → 12V Buck；12V 备用源与主 Buck 经二极管 OR 汇流。'
        'OR 母线同时供给驱动模块端口及 5V Buck，5V 再供给外设和 3.3V LDO，3.3V 供给 MCU。'
        '两个 Buck 沿用 LTC3864 功能参考，LDO 使用 TLV75533 行为近似。')
    rows=[]
    for key,row in manifests['normal'].get('loads',{}).items():
        config=row['config'];stages=config.get('stages',[])
        demand='；'.join(f"{s['power_W']/config['nominal_voltage_V']*1000:g}mA" if s['mode']=='I' else f"{s['power_W']:g}W({s['mode']})" for s in stages)
        timings=' / '.join(f"{s['after_s']*1000:g}" for s in stages)+' ms'
        conditions=[f"本地{config['on_V']:g}/{config['off_V']:g}V"]+[
            f"{c['port']} {c['on_V']:g}/{c['off_V']:g}V" for c in config.get('ready_conditions',[])]
        rows.append([key,demand+'\n'+timings,'；'.join(conditions)+f"；等待{config['delay_s']*1000:g}ms"])
    table(doc,['负载端口','总运行需求及阶段','释放条件与等待'],rows,widths=[1.05,2.15,3.9])
    paragraph(doc,'上述电流、功率、延时与门限是用于验证机制的示例设定，并非某块控制板的实测数据。'
        '阶段功耗为总量；时间从每次连续就绪并释放等待后起算。任何依赖跌至复位门限即退出运行，电容残压仍继续求解。',small=True)
    doc.add_heading('2 四个工况如何判断',1)
    table(doc,['试验','输入变化','求解状态'],[
        [LABELS[name],scenario_inputs(manifests[name]),
         results[name]['status']+'；'+('报告异常' if results[name].get('report_error') else '求解状态不是场景结论')]
        for name in LABELS],widths=[1.55,3.55,2.])
    table(doc,['试验','独立验收结论','检查结果说明'],[
        [LABELS[name],audit_states[name]['text'],audit_states[name]['details']] for name in LABELS],widths=[1.55,1.8,3.75])
    if audit_info:
        paragraph(doc,'跨工况检查：'+('未通过 '+ '；'.join(audit_info['cross_case_failures']) if audit_info['cross_case_failures'] else
            ('跨工况一致性与相对时序检查通过' if passed else '结论待完整证据核对'))+'。验收凭据SHA256：'+audit_info['sha256'],small=True)
    else:paragraph(doc,'尚未载入独立验收JSON。请先运行check_staged_sequence_evidence.py，再用--audit指定其输出；本总览保留未知状态。',small=True)
    paragraph(doc,'所有工况保持同一组转换器器件与补偿。主、备输入的min/max在此例分别相同，均为24V/12V；'
        '本例不包含输入电压容差、全温及制造散差验证。硬件摘要 SHA256：'+receipt['hardware_sha256'],small=True)
    doc.add_page_break()
    doc.add_heading('3 源电流与保护实际观察',1)
    rows=[]
    for name in LABELS:
        r=results[name]
        for source in r.get('summary',{}).get('sources',[]):
            ls, fs = source.get('limit_state',{}), source.get('fault_state',{})
            rows.append([LABELS[name],source['id'],number(source.get('supply_current_peak_A')),
                number(source.get('current_limit_A')),number(ls.get('active_time_s'),1000),
                number(fs.get('on_count'))+' / '+number(fs.get('off_count'))])
    table(doc,['试验','输入源','内部供流峰 A','限幅 A','限流累计 ms','故障入/退'],rows,widths=[1.55,1.15,1.,.8,1.25,1.35])
    paragraph(doc,'源保护是显式有限源阻与CV/CC、折返或打嗝行为，缺少真实电源控制环带宽。'
        '源输入限流与 Buck 的逐周期开关采样限流是两级不同保护；不能互相替代。')
    doc.add_heading('3.1 单元启机与观察窗电流 / OCP',2)
    ocp_rows=[]
    for name in LABELS:
        for unit in results[name].get('summary',{}).get('units',[]):
            if unit.get('topology')=='LDO':continue
            ocp=unit.get('ocp',{})
            ocp_rows.append([LABELS[name],unit['id'],number(ocp.get('equivalent_sense_current_peak_A')),
                number(ocp.get('cycle_ceiling_V'),1000)+'mV / '+number(ocp.get('sense_resistor_ohm'),1000)+'mΩ',
                ocp_observation(ocp)])
    table(doc,['试验','单元','等效采样峰 A','CS门限 / Rs','限流与故障观察'],ocp_rows,widths=[1.35,1.05,1.0,1.35,2.35])
    paragraph(doc,'表中峰值直接来自完整观察窗（含启机、运行与关机）的RAW分析，并非只截取启动时段。'
        '本示例两个Buck声明的95mV / 20mΩ对应标称4.75A采样门限；它不是输入端口峰值限制。'
        '周期计数是可观察下界；未知不等于未发生限流，FAULT=0也不能单独证明保护合格。'
        'LDO没有独立CS探针，本表不套用Buck的限流结论；其端口电流与行为限流假设见各工况子报告。',small=True)
    capacitive=[(key,row['config']) for key,row in manifests['normal'].get('sources',{}).items() if row['config'].get('output_capacitance_F',0)>0]
    if capacitive:
        paragraph(doc,'源端输出储能设定：'+'；'.join(key+' '+number(config['output_capacitance_F'],1e6)+'µF / '+number(config['output_esr_ohm'])+'Ω ESR' for key,config in capacitive)+
            '。这些数值是本例工程假设，须用实际供电器资料或实测值替换；不作为收敛已修复的证明。')
        table(doc,['试验','输入源','限流器供流峰 A','源端口供流峰 A'],[
            [LABELS[name],source['id'],number(source.get('limiter_supply_current_peak_A',source.get('supply_current_peak_A'))),number(source.get('port_supply_current_peak_A'))]
            for name in LABELS for source in results[name].get('summary',{}).get('sources',[])],widths=[1.8,1.4,1.95,1.95])
        paragraph(doc,'内部限流器只限制自身供流，限流器后的电容可额外向端口放电。端口电流短时超过内部限流值不单独判为过流；休眠时残存电容仍可供能。独立验收按完整RAW分别核对内部限流、端口电流及电容电荷守恒。',small=True)
        if any(row.get('port_current_derivation')=='source-minus-capacitor' for manifest in manifests.values() for row in manifest.get('sources',{}).values()):
            paragraph(doc,'本轮声明的源端口电流由 −I(内部源)−I(源端电容) 组合派生，未额外串联理想电压源。KCL组合本身不是独立验证；另外用全RAW电流积分与 C·Δ(V端口−ESR·I电容) 对照储能电荷。',small=True)
    approximations=model_approximations(manifests)
    if approximations:
        doc.add_heading('3.2 本轮模型采用的数值近似',2)
        paragraph(doc,'以下内容读取本轮冻结模型清单。它们改变模型转折的表达方式，不表示降低求解器精度，也不能替代真实器件动态模型。',small=True)
        for text in approximations:paragraph(doc,text,small=True)
    doc.add_heading('4 各负载阶段与重复启动',1)
    rows=[]
    for name in LABELS:
        for row in results[name].get('summary',{}).get('loads',[]):
            stages=row.get('stage_observations',{})
            observed=stages.get('stages',[])
            first=' / '.join(number(s.get('first_entry_s'),1000) for s in observed)
            rows.append([LABELS[name],row['id'],first,
                number(stages.get('reset_count'))+' / '+number(stages.get('restart_count')),
                number(row.get('active_current_peak_A'))])
    table(doc,['试验','负载','各阶段首次进入 ms','复位/重启','运行峰 A'],rows,widths=[1.55,1.15,2.05,1.25,1.1])
    paragraph(doc,'上述数值来自完整RAW统计。运行耗流不包括额外电容充电、泄放与待机，端口总电流单独列在子报告中。'
        '故障工况下某阶段没有进入，是必须保留的真实观察。首次达到输出电压不代表此后没有塌陷。',small=True)
    doc.add_page_break()
    doc.add_heading('5 关键波形与证据入口',1)
    for name in ('normal','warm_restart'):
        directory=directories[name]
        # Reports render their figures into this directory; no new numeric solve.
        images=list(directory.rglob('voltages.png'))
        if len(images)==1 and results[name].get('simulation_complete') is True:
            figure(doc,images[0].read_bytes(),LABELS[name]+'：同次瞬态的实际输出电压',width=6.8)
        else:paragraph(doc,LABELS[name]+'：完整电压波形缺失、歧义或本次仿真未完成，未采用其他运行图片。',small=True)
    doc.add_heading('6 适用边界与下一步实物标定',1)
    for text in [
        'LTC3864参考CS门限为95mV、Rsense为20mΩ，标称采样支路限流约4.75A；其电感典型饱和电流参考4.2A。此例负载下的实际峰值与最坏OCP匹配是不同检查，尚不能宣称电感已被全工况可靠保护。',
        'LDO把典型550µs启动和355mA短路电流映射为线性参考与固定限流，没有完整复刻TLV755P的电压相关折返、温度保护及实际EN/PG引脚。',
        '各转换器VCC仍为理想偏置，外部多轨就绪是电压监控近似。尚未建立启动电阻、辅助绕组接管、复位芯片、I/O反向供电和固件异常耗流模型。',
        '所有返回共SPICE 0。布线阻抗、寄生、温升及隔离返回需结合实物另核。下一步用真实板卡各电源脚的I(t)/P(t)、复位门限和供电器保护曲线替换示例设定。',
    ]: paragraph(doc,text,small=True)
    report_references(doc,[
        ('LTC3864 Rev C','https://www.analog.com/media/en/technical-documentation/data-sheets/ltc3864.pdf'),
        ('TLV755P SBVS320D','https://www.ti.com/lit/ds/symlink/tlv755p.pdf'),
        ('ADI 启动浪涌说明','https://www.analog.com/en/resources/analog-dialogue/articles/preventing-start-up-issues-due-to-output-inrush-in-switching-converters.html'),
    ])
    destination=folder/(title+'.docx')
    doc.save(destination)
    entries=['# 完整电源树联合启停验证','',
        '桌面程序的画布中选择“打开工程”，加载 `完整分阶段电源树示例.json`；点击“联合启停仿真”调整输入源、各电源、负载和支路。',
        '编辑表格后先“保存列表”，再“应用并保存”；保存系统工程后设置随JSON保存。运行需要本机LTspice。','',
        '四个工况使用相同转换器硬件。负载阶段、源能力及门限均有明确示例假设，不作为实物通过声明。',
        '总览：`'+destination.name+'`。独立RAW验收工具：`tools/check_staged_sequence_evidence.py`。',
        '总体独立验收：'+('四个声明场景符合预期，非硬件验收。' if passed else '尚未全部符合预期；见报告中的未知/失败项。'),'']
    for name in LABELS:
        d=directories[name].relative_to(folder).as_posix()
        entries += ['- '+LABELS[name]+'：`'+d+'`，求解状态 `'+results[name]['status']+'`；独立验收：'+audit_states[name]['text']+'。含本次参数、分析与仿真证据。']
    entries += ['', '失败或超时的早期尝试在原目录保留，不作为本次成功证据。验收通过仅指符合所声明的试验预期；故障捕获不等于负载启动成功。',
        '本轮未改动用户实际画布，未同步公司项目或纯浏览器路径。','']
    (folder/'README.md').write_text('\n'.join(entries),encoding='utf8')
    audit_copy=folder/'独立RAW验收.json'
    if args.audit is not None:
        if args.audit.resolve()!=audit_copy.resolve():audit_copy.write_bytes(args.audit.read_bytes())
    index=dict(schema='power.staged-sequence-package/1',all_scenario_expectations_met=passed,
        hardware_passed=None,audit=audit_info,conclusions=audit_states,
        report=dict(file=destination.name,sha256=digest(destination)),
        selected_runs={name:directories[name].relative_to(folder).as_posix() for name in LABELS})
    (folder/'package-evidence.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    archive=write_archive(folder,directories,destination.name,args.audit is not None) if args.zip else None
    print(json.dumps(dict(report=str(destination),sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),archive=archive),ensure_ascii=False))


if __name__=='__main__':main()
