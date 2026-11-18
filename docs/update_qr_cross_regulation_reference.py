"""Scoped, repeatable QR cross-regulation addition to the editable reference.

Run using the bundled document Python after numerical verification. The marked
chapter is replaced in place; previous reference chapters and figures survive.
The fixed-frequency multi-output beginner tutorial is deliberately unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx_layout import paragraph, table, _font
import word_math as wm

TARGET = ROOT/'docs/reference/计算方法与公式说明.docx'
START = 'qr_cross_regulation_start_v1'
END = 'qr_cross_regulation_end_v1'
QA = ROOT/'artifacts/qr-cross-20261108/documentation'


def _mark(doc, name, ident):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.line_spacing = Pt(1)
    start = OxmlElement('w:bookmarkStart')
    start.set(qn('w:name'), name)
    start.set(qn('w:id'), str(ident))
    end = OxmlElement('w:bookmarkEnd')
    end.set(qn('w:id'), str(ident))
    p._p.extend([start, end])


def _remove_previous(doc):
    active = False
    for node in list(doc.element.body):
        marks = [e.get(qn('w:name')) for e in node.iter(qn('w:bookmarkStart'))]
        if START in marks:
            active = True
        if active:
            doc.element.body.remove(node)
        if END in marks:
            break


def add_chapter(doc, *, symbols=None):
    aliases = {
        'LA': 'L_A', 'RA': 'R_A', 'iA': 'i_A', 'uA': 'u_A',
        'Lres': 'L_res', 'Ceff': 'C_eff', 'Tv': 'T_v', 'Tdemag': 'T_demag',
        'Tblank': 'T_blank', 'Twait': 'T_wait', 'Tperiod': 'T_s',
        'kvalley': 'n', 'Vcapb': 'V_c,b', 'Vportb': 'V_out,b', 'Vblockb': 'V_B,b',
        'Vrefj': 'V_ref,j', 'Psetj': 'P_set,j', 'Rloadj': 'R_load,j',
        'Vportj': 'V_out,j', 'Iloadj': 'I_load,j', 'Qdj': 'Q_D,j',
        'iDj': 'i_D,j', 'Idavgj': 'I_D,j,avg', 'Fqj': 'F_Q,j',
        'Vmaxj': 'V_max,j', 'Vminj': 'V_min,j', 'Senvj': 'S_env,j',
        'Scrossj': 'S_cross,j', 'Vhighj': 'V_high,j', 'Vlowj': 'V_low,j',
        'Lii': 'L_ii', 'Ljj': 'L_jj', 'Lij': 'L_ij', 'kij': 'k_ij',
        'fmax': 'f_max', 'ipend': 'i_p,end', 'i0': 'i_0', 'iend': 'i_end',
        'Tminoff': 'T_off,min', 'Tlightoff': 'T_off,light',
        'Vchip': 'V_COMP,chip', 'Vcscommand': 'V_CS,cmd', 'Vcs0': 'V_CS,0',
        'Vclamp': 'V_clamp', 'Qclamp': 'Q_clamp', 'Rclamp': 'R_clamp',
        'Cclamp': 'C_clamp', 'Vclripple': 'ΔV_clamp,est',
        'Twindow': 'T_w', 'Δtk': 'Δt_k', 'iknext': 'i_k+1', 'ik': 'i_k',
        'Iwindowavg': 'I_avg', 'Iwindowrms': 'I_rms',
        'εIj': 'ε_I,j', 'Iwindavgj': 'I_s,j,avg', 'Vportavgj': 'V_out,j,avg',
        'vZrep': 'v_Z,rep', 'vwindj': 'v_s,j', 'Naux': 'N_aux', 'Nsj': 'N_s,j',
    }
    wm.ALIASES.update(aliases)
    wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)
    equations = 0
    def E(text):
        nonlocal equations
        equations += 1
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = 1.
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(7)
        p._p.append(wm.element('oMath', *wm.math_nodes(text)))
        _font(p.add_run(f'   (QRCR{equations:02d})'), 9)
    def P(text):
        p = paragraph(doc, text)
        p.paragraph_format.line_spacing = 1.15
        return p
    def H(text):
        p = doc.add_heading(text, 2)
        for run in p.runs:
            _font(run, 13, True)
        return p
    def S(text):
        p = paragraph(doc, text)
        p.paragraph_format.line_spacing = 1.02
        p.paragraph_format.space_after = Pt(5)
        for run in p.runs:
            _font(run, 10)
        return p
    p = doc.add_heading('20  准谐振反激的多路交叉调整率', 1)
    p.paragraph_format.page_break_before = True
    for run in p.runs:
        _font(run, 17, True)
    P('本章解释 QR 多路输出在独立负载变化下的稳态电压求解。未启用耦合矩阵时仍使用第3章与14.2节的标称匝比近似；启用有效非理想矩阵后，以同一套硬件联立绕组换流、电荷平衡、退磁结束和谷底时序。所选一路维持防反管前的反馈目标，其余输出电压为未知量，不能将参考匝比电压直接当作交叉调整率结果。')
    H('20.1  输入数据与测量节点')
    table(doc, ['输入组', '需要的数据及含义'], [
        ('需求与负载', 'Vinmin/Vinmax、唯一SSR反馈路、反馈端口目标、各路最大和最小功耗；最小功耗包含实际永久预负载。'),
        ('同一副变压器', '整数Np/Ns、正定自感互感矩阵或有效kij、几何MLT及裸铜面积生成的DCR。扫描不重新选匝或修改耦合。'),
        ('整流及防反', '每路固定整流压降、可选防反压降与主开关/采样电阻；曲线损耗不等于换流已改为非线性二极管。'),
        ('固定RCD硬件', '在参考名义点按Kc选定R/C并冻结；角点不重新选R，平均钳位电压由钳位电荷与电阻耗散联立求解。'),
        ('QR时序', '总有效谐振电容、L6565参考消隐时序及稳态电流指令映射；界面f_sw仅为设计频率上限。'),
    ], [1.35, 5.65])
    P('输出电压、负载和电压包络位于输出防反二极管之后；SSR位于反馈路防反管之前。各路按名义参考电压把功耗设置换算成恒阻负载，端口电压改变后实际功率随之变化。扫描中固定的是电阻，并非恒功率负载。')
    E('Rloadj=Vrefj²/Psetj')
    E('Iloadj=Vportj/Rloadj')
    E('Vcapb=Vportb+Vblockb')
    if symbols:
        symbols(
            ('j，b','一般输出路号、唯一的 SSR 主反馈路号','—'),
            ('Rloadj，Psetj','第 j 路恒阻负载及用来换算电阻的功耗档位','Ω；W'),
            ('Vrefj，Vportj，Iloadj','第 j 路的参考电压、求出的端口电压、负载电流','V；V；A'),
            ('Vcapb，Vportb，Vblockb','反馈路防反管前的电容端电压、防反管后的端口电压及防反压降','V'),
        )
    P('Psetj=0表示真实开路，不能用微小正功耗偷换。没有泄放、结电容和控制器间歇工作模型时，此角点明确保留为未支持；成功角点只能形成不完整观察范围。全部最小功耗等于最大功耗时，没有覆盖交叉负载变化。')
    H('20.2  独立绕组换流与电荷平衡')
    E('Lij=kij√(Lii·Ljj)')
    E('LA·d iA/dt+RA·iA=uA')
    if symbols:
        symbols(
            ('Lii，Ljj，Lij，kij','绕组开路自感、互感项和逐对耦合系数','H；H；H；—'),
            ('A，LA，RA','当前导通绕组集合及对应的电感、电阻子矩阵','—；H；Ω'),
            ('iA，uA，t','导通集合的电流向量、所施加的端电压向量及时间','A；V；s'),
        )
    P('每一个导通集合使用其电感子矩阵、DCR和施加电压推进电流。二极管仅允许正向电流：阻断支路满足反偏约束，电流降至零后切换导通集合。这样可以得到轻载路的窄脉冲与不同支路的退磁时刻，不按功率比例分配副边电流。主开关关断后的漏感换流使用本周期平均钳位电压；电荷积分同时保留各路整流支路与原边RCD钳位支路。')
    E('Qdj=∫_0^Tperiod iDj(t) dt')
    E('Fqj=Qdj−Iloadj·Tperiod=0')
    E('Idavgj=Qdj/Tperiod')
    if symbols:
        symbols(
            ('Tperiod，iDj(t)','本工况求出的开关周期、第 j 路的瞬时整流电流','s；A'),
            ('Qdj，Fqj，Idavgj','一个周期的整流电荷、电荷平衡残差、整流平均电流','C；C；A'),
        )
    P('每路一个电荷残差。再加主反馈电压约束、QR周期条件及下述钳位功率平衡，调整导通时间、非反馈电压与平均钳位电压，使所有方程共同满足。不能只让总输出功率平衡而忽略某一路电容仍在充电。输出电容直流端电压在一个开关周期内保持不变，纹波由现有每颗C/ESR/ESL支路后处理重建；大纹波、动态交叉耦合和瞬态ESR反馈尚需电路仿真。')
    P('RCD在参考名义工作点按Kc选定实际Rclamp与Cclamp，随后随同硬件冻结。轻重载角点不能继续强制相同Kc，更不能各自重选电阻。Qclamp为矩阵换流解每周期流入钳位支路的正向电荷；小纹波下令该支路平均输入功率等于固定电阻耗散，联立求得Vclamp。Vclamp是相对输入母线的钳位电容电压，不是完整MOS漏源电压。')
    E('Vclamp·Qclamp/Tperiod=Vclamp²/Rclamp')
    E('Vclripple=Qclamp/Cclamp')
    if symbols:
        symbols(
            ('Kc，Vclamp','参考点钳位电压与反射电压之比、本角点相对输入母线的平均钳位电压','—；V'),
            ('Qclamp','一个周期流入钳位支路的正向电荷','C'),
            ('Rclamp，Cclamp','由参考点选定并在整个扫描中固定的钳位电阻和电容','Ω；F'),
            ('Vclripple','按总电荷对钳位电容充电得到的纹波上界估算','V'),
        )
    P('第二式把全部钳位电荷计入C，忽略充电期间同时流过R的泄放，只用作钳位纹波的保守上界估算与小纹波适用提示；不是求出了完整RC瞬态。当纹波不可忽略时，第一式中的平均电压近似、换流时刻及峰值应力均需实际电路复核。独立名义工作点没有冻结RCD硬件字段时，保留恒Kc兼容近似并明确注明；它不能冒充同一固定RCD硬件下的完整负载扫描。')
    H('20.3  从退磁结束确定变频周期')
    P('每周期从全部绕组传导电流为零开始，关断后依次求二极管换流，直到所有储能传导支路退磁结束；不是用反馈路三角电流的理想下降时间替代其他绕组。恒定等效谐振电容的首谷等待从退磁结束开始计时。Lres取矩阵原边自感；Ceff先取显式正值qr_cds_pf，否则取MOS的Coss，再加折算到原边的绕组寄生电容cw_primary。它是恒定等效电容，不是沿Vds积分的非线性Coss。')
    E('Tv=π√(Lres·Ceff)')
    E('Twait=(2·kvalley−1)·Tv')
    E('Tperiod=Ton+Tdemag+Twait')
    E('fs=1/Tperiod')
    if symbols:
        symbols(
            ('Lres，Ceff','近似谷底时序使用的原边开路自感及折算到原边的有效谐振电容','H；F'),
            ('Tv，n','从退磁完成到首谷的理想等待时长及被选中的谷底序号','s；—'),
            ('Ton，Tdemag，Twait','主开关导通时间、关断到所有传导支路退磁结束的时间、退磁后等待时间','s'),
            ('fs，fmax','当前角点实际开关频率和设计频率上限','Hz'),
        )
    P('n从1开始，n=1是退磁后的首谷。软件用原边RL导通斜坡计算原始CS信号，周期一阶RC滤波保留上一周期残余，在Ton减去比较器延时处取所需CS指令，再按下式反推参考芯片COMP及关断消隐。式内电压均以V代入，Vcs0为配置的QR电流钳位基准。')
    E('Vchip=2.5+3·Vcscommand/Vcs0')
    E('Tblank=max(Tminoff,Tlightoff+(Tminoff−Tlightoff)·(Vchip−2.5)/0.7)')
    if symbols:
        symbols(
            ('Vchip，Vcscommand，Vcs0','参考芯片 COMP 电压、稳态所需采样指令、电流钳位基准电压','V'),
            ('Tblank，Tminoff，Tlightoff','关断后的 ZCD 消隐时间、较高 COMP 时最短消隐、轻载消隐时间','s'),
        )
    P('选择满足“退磁时间加谷底等待不小于关断消隐”的最早谷底；更早谷底若已允许则不能跳过。所需CS指令须低于VFF修正的逐周期钳位，导通时间须满足最小导通、前沿消隐、比较器延时及最大导通约束。无单周期自洽谷底或超出这些约束时保留失败原因，不能用理想匝比补结果。界面f_sw不强迫电路按固定时钟开通，也不把周期简单延长到1/fmax；实际求得的fs另与设计上限比较。超过上限属于需复核，不代表通过延长周期就实现了另一颗控制器的功能。')
    P('ST AN1326式(4)的π√(LpCd)是退磁完成到首个漏极谷底的时间。仿真设置中“四分之一谐振周期的附加ZCD延时”相对的是下降沿检测点，时间原点不同，不能将其直接替代本式。当前模型采用无损、恒定Ceff的谷底时序近似；不解析完整谷底负向原边电流，也不模拟真实ZCD的RC、阈值误差、振铃衰减、启动定时器或保护动态。')
    H('20.4  角点扫描与结果判定')
    P('每路取最小、最大两档负载，去掉重复档位；三路最多8种组合，六路最多64种，再分别检查两个输入端点。所有角点沿用同一磁芯、整数匝数、DCR、互感、RCD电阻与电容、器件和补偿。每个角点独立求得电压、平均钳位电压、实际频率、导通时间、退磁及谷底等待；不预设某一路轻载、其他路重载一定最坏。')
    E('Senvj=100·(Vmaxj−Vminj)/Vrefj')
    E('Scrossj=100·(Vhighj−Vlowj)/Vrefj')
    if symbols:
        symbols(
            ('Vmaxj，Vminj','第 j 路在全部有效输入及负载角点中的最高、最低端口电压','V'),
            ('Vhighj，Vlowj','固定输入电压和本路电阻时，同一组角点中的最高、最低端口电压','V'),
            ('Senvj，Scrossj','全包络电压跨度、各组纯交叉电压跨度中的最大值','%'),
        )
    P('Senvj对全部有效角点求电压最大值与最小值，包含本路负载和输入变化。Scrossj先固定Vin及本路电阻，仅改变其他路负载，再取各组中的最大跨度。每个极值均保存角点编号和全部路的负载条件。电荷残差、退磁或数值求解失败保留具体原因，失败角点不能以0V或匝比值填补。频率超过设计上限可保留已求得的工作点，但需单独标记超限；求解完整不等于设计约束全部合格。')
    H('20.5  与电路仿真形成同条件对照')
    P('仿真侧按相同硬件、输出节点和恒阻负载运行角点，统计末段稳定窗口的端口平均电压，并检查保护状态、实际QR边沿及相邻窗口漂移。计算完整、仿真完整和两者都完整分别记录；任一方缺失时，另一方的已得观察值可以保留，但不能给出完整对比通过结论。')
    doc.add_heading('电流按同一物理支路比较',3)
    P('原边绕组 LP 的电流以输入母线流入绕组为正，包含主开关导通电流和关断后的 RCD 换流尾部。MOS 沟道电流以漏极流向源极为正，关断时不承担同一段钳位电流。计算的 I_p_avg、I_p_rms、I_p_pk 对应 I(LP)，I_sw 系列对应 MOS 沟道；峰值取窗口内正向最大值，反向谷值另列。不能把 MOS 电流的有效值用作物理原边绕组电流的对照值。')
    P('LTspice 的受控开关 Smain 在 RAW 文件中采用与上述漏源方向相反的探针方向，读取后先变号，再统计平均值、正峰和功率。沟道总峰值包含开通时 Coss 放电电流；它与向变压器传能的电流峰值分列，不能将前者直接当作 RL 传能模型的计算误差。')
    P('副边绕组电流与整流二极管的导通电流也要分开。电路中的绕组电流可能同时供给整流电流、Cj 位移电流及外接 RC 支路；矩阵 RL 模型保留传导换流，未求解 Coss 与 Cj 的高频电流。因此轻载路的窄脉冲应先检查原始波形及电流分量，再解释峰值或有效值差异，不对真实尖峰平滑后重新判定。')
    P('CS 滤波使用采样电压的高输入阻抗副本，内部一阶 RC 的时间常数等于配置值，不从功率级采样电阻抽取电流。实现传递函数所用的内部 1 Ω 电阻不是外部滤波电阻；若将它直接接到采样节点，会改变源极电流分配和有效滤波时间常数。')
    doc.add_heading('采用实际完整周期的时间积分',3)
    P('QR 的周期由门极实际上升沿界定。软件选取至少八个连续完整周期，保留原始自适应采样及窗口边界的线性插值。时间采样密度不均匀时，直接对样本求平均会过度放大高频边沿的权重；采用每一时间段的实际长度进行积分。')
    E('Twindow=ΣΔtk')
    E('Iwindowavg=Σ(Δtk(ik+iknext)/2)/Twindow')
    E('Iwindowrms²=Σ(Δtk(ik²+ik·iknext+iknext²)/3)/Twindow')
    if symbols:
        symbols(
            ('Twindow、Δtk','连续完整开关周期覆盖的总窗口，以及第 k 个原始线性插值段的长度','s'),
            ('ik、iknext','第 k 段起点和终点的带符号电流；求和覆盖窗口内所有分段','A'),
            ('Iwindowavg、Iwindowrms','相同窗口内的带符号平均电流和有效值','A'),
        )
    P('平均值按梯形积分；均方值按线性电流平方的解析积分计算。峰值和反向谷值直接取原始分段波形的极值，未使用固定参考时钟截取半个脉冲。频率由完整周期数除以窗口长度得到。Coss 位移电流、MOS 沟道和二极管导通电流分别记录。')
    doc.add_heading('平稳电压还需满足逐路电荷平衡',3)
    E('εIj=Iwindavgj−Vportavgj/Rloadj')
    if symbols:
        symbols(
            ('Iwindavgj、Vportavgj','同一完整周期窗口内第 j 路绕组平均电流与防反管后端口平均电压','A；V'),
            ('Rloadj、εIj','本次硬件冻结的负载电阻，以及流入输出电容组的平均净充电电流','Ω；A'),
        )
    P('该检查适用于导出工程的恒阻负载；周期稳定时，绕组端并联寄生电容与 RC 支路的平均电流为零。当前判定阈值为负载电流的 1% 与 1 µA 中较大者，属于软件的稳态验收阈值。若电压看似平坦但仍有净充电，保留波形并标为尚未满足电流稳态，不输出有效的电流误差结论。')
    doc.add_heading('从所选绕组取得退磁信号',3)
    P('L6565 以 ZCD 的下降沿启动下一次导通，下降沿必须代表有效退磁信息。仿真设置 qr_zcd_winding 为 −1 时，优先选择非反馈输出中匝数最少的一路；单路使用 OUT1。设为 1 至 6 时指定对应输出绕组，0 保留历史原边 drain−Vin 端电压复制。输出路号越界时停止导出，设置随工程保存。')
    E('vZrep=(Naux/Np)·(Np/Nsj)·vwindj')
    if symbols:
        symbols(
            ('vwindj、vZrep','所选绕组 rectj 相对 sgnd 的瞬时端电压，以及送入 ZCD 滤波前的等效副本电压','V'),
            ('Naux/Np','qr_aux_ratio 设置的等效检测辅助绕组与原边匝数比','1'),
            ('Np、Nsj','原边与所选输出绕组的实际匝数','匝'),
        )
    P('该电压副本具有理想隔离、不消耗绕组功率；它不表示把隔离次级接到原边地，也不代替真实辅助绕组供电。旧原边端电压包含漏感换流尖峰，可能在副边尚有传导电流时越过 ZCD 阈值并引起提前开通。应同时检查开通前各路电流、ZCD、门极和全程 Vds 峰值，再调整取样、消隐及 RC 阻尼；不能仅靠增大 Coss 消去症状。该选源是通用行为模型的实现选项，芯片实际外围连接仍按数据手册设计。')
    P('比较前需核对各路电阻、固定Vf、DCR、自感互感、固定RCD电阻/电容、反馈路与谐振电容。平均钳位电压虽已随负载联立变化，仍不同于电路中RCD电容逐时刻充放电及寄生振铃；恒定电容等待也不包含二极管Cj和真实ZCD滤波。这些差异可能改变换流与谷底选择。解析低频环路仍采用按匝比折算负载及全部电容支路的QR平均模型，不因新增跨调求解就自动宣称成为完整多端口环路。')
    H('20.6  原厂依据与项目假设')
    S('ST AN1326《L6565 quasi-resonant controller》第3页式(4)及第4页“QR OPERATION TIMING AND ENERGETIC RELATIONSHIPS”给出退磁、谷底等待和变频关系，且明确其理想推导忽略变压器非理想。本软件的矩阵换流、电荷残差、固定RCD平均功率平衡和求根算法为项目实现，不是该应用笔记验证过的通用数值模型。')
    S('https://www.st.com/resource/en/application_note/an1326-l6565-quasiresonant-controller-stmicroelectronics.pdf')
    S('ST L6565数据手册第2页引脚说明及ZCD消隐/轻载降频章节说明退磁下降沿开通与电流指令相关消隐。软件只用其逻辑原型建立稳态近似；没有独立原厂硅模型验证。')
    S('https://www.st.com/resource/en/datasheet/l6565.pdf')
    S('TI SSZTD98第1节图1至图3说明漏感换流形成的共同电压台阶会给轻载输出峰充。它支持保留独立绕组换流的物理理由，不验证当前QR算法、容差或某个最坏组合。')
    S('https://www.ti.com/document-viewer/lit/html/SSZTD98/GUID-56A31413-780F-4984-B393-18DC28330328')
    S('TI SLUP261第32页VI.A节与图35说明RCD电阻耗散、钳位电容保持低纹波，以及钳位电压随负载和输入改变；第13、16页讨论钳位电压对交叉调整率的影响。它支持冻结实际R/C再检查各工况，不支持把所有角点都强制为同一Kc。当前Qclamp联立与纹波上界仍为项目数值实现。')
    S('https://www.ti.com/seclit/ml/slup261/slup261.pdf')
    return equations


def update_document(doc, *, symbols=None):
    _remove_previous(doc)
    anchor = next(p._p for p in doc.paragraphs if p.text.startswith('附录 A'))
    before = set(doc.element.body)
    _mark(doc, START, 9200)
    equations = add_chapter(doc, symbols=symbols)
    _mark(doc, END, 9201)
    for node in [e for e in doc.element.body if e not in before and e.tag != qn('w:sectPr')]:
        anchor.addprevious(node)
    if symbols is None and doc.tables[0].cell(0, 0).text == '章节':
        nav = doc.tables[0]
        row = next((r for r in nav.rows if r.cells[0].text == '20'), None)
        if row is None:
            nav._tbl.append(deepcopy(nav.rows[-1]._tr))
            row = nav.rows[-1]
        for cell, text in zip(row.cells, ['20', '准谐振反激的多路交叉调整率', 'qr_coupled / cross_regulation']):
            cell.paragraphs[0].clear()
            _font(cell.paragraphs[0].add_run(text), 10)
    for p in doc.paragraphs:
        if p.text.startswith('软件计算内核详解'):
            p.runs[0].text = '软件计算内核详解  含QR多路交叉调整率增补  2026-11-08'
            for run in p.runs[1:]:
                run.text = ''
        elif p.text.startswith('软件将 QR 视为单谷底 BCM'):
            p.text = '未启用绕组耦合矩阵时，软件将QR视为单谷底BCM：每周期理想退磁到零，再等待半个L-Coss谐振周期。启用有效非理想矩阵后的多路独立换流、变频周期及交叉调整率另见第20章。界面f_sw为设计频率上限。'
        elif p.text.startswith('环路在此模式下复用低频 DCM 单极点对象'):
            p.text = 'QR低频环路按每周期电荷平均与变频周期的局部导数求得，保留各颗输出电容ESR；多路负载及电容按Ns/Ns反馈路折算。该环路仍为理想匝比约化，不包含第20章独立换流的完整多端口动态、谷底序号切换或真实光耦延迟。'
    return equations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=TARGET)
    args = parser.parse_args()
    QA.mkdir(parents=True, exist_ok=True)
    backup = QA/'before-reference.docx'
    if not backup.exists():
        backup.write_bytes(TARGET.read_bytes())
    doc = Document(TARGET)
    equations = update_document(doc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)
    print(json.dumps(dict(file=str(args.output), added_equations=equations,
        total_math=len(doc.element.xpath('.//m:oMath')), tables=len(doc.tables),
        images=len(doc.inline_shapes), sha256=hashlib.sha256(args.output.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
