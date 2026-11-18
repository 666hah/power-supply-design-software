"""Native Word math and result tables for the coupled flyback model."""
from docx_layout import paragraph, table, equation, section


def add_coupling_reference(doc, *, symbols=None):
    section(doc,'16  绕组逐对耦合与钳位电压')
    paragraph(doc,'绕组间的漏磁会改变各路整流器的导通时刻。固定频率 SSR 反激启用耦合矩阵后，软件在每个开关周期内求这些时刻及支路电流。六路输出加上原边构成七阶矩阵，共有二十一对不同绕组。关闭矩阵时采用第 14 章的标称分配。QR 使用第 20 章的变频求解，MP6005 PSR 和有源钳位正激沿用各自的模型。')
    doc.add_heading('16.1  自感互感与输入检查',2)
    equation(doc,'M_ij = k_ij·√(L_ii·L_jj)')
    equation(doc,'v_i = R_i·i_i + Σ_{j=1}^{n}(L_ij·di_j/dt)')
    if symbols:
        symbols(
            ('i，j，n','绕组编号与参与建模的绕组总数，含原边','—'),
            ('L_ii，L_jj','第 i、j 个绕组的开路自感','H'),
            ('L_ij，M_ij，k_ij','矩阵非对角互感项、相同互感量及逐对耦合系数','H；H；—'),
            ('v_i，R_i，i_i，i_j','第 i 支路端电压和电阻、第 i、j 支路电流，电流以流入同名端为正','V；Ω；A；A'),
            ('di_j/dt','第 j 绕组电流的瞬时变化率','A/s'),
        )
    paragraph(doc,'Lp 为原边开路自感，各副边自感由 Lp/(Np/Nsi)² 得到。先解析实际整数 Np、各 Ns、线径和股数，再构造电感矩阵；非反馈路的近似电压由主反馈电压乘副边匝数比得到。矩阵电流参考流入同名端，副边同名端位于输出回路端，整流导通时副边电压为负。这里只支持这种固定同名端接法及非负 kij。')
    paragraph(doc,'输入范围为 0≤kij≤1，对角线为 1，互易矩阵须对称、半正定。各对分别在范围内并不能保证矩阵可实现；非理想时要求正定，不对非法矩阵添加虚构的小电感。全部 kij=1 是奇异的理想极限，显式返回原标称分配，不能据此声称唯一预测各路实际分流。其他奇异情形暂不支持。')
    equation(doc,'Lsc = Lp·(1−k²)')
    if symbols:
        symbols(
            ('Lsc，Lp，Lσ','副边短路时原边测得的电感、原边开路自感、历史 RCD 模型的等效漏感','H'),
            ('k，K','两绕组间的磁耦合系数、历史 RCD 用的无量纲输入量','—'),
        )
    paragraph(doc,'上式仅为两绕组、另一绕组短路时的原边漏感定义。多绕组全副边短路等效量用矩阵消元求得，不把每对漏感简单相加。历史 RCD 输入 K 仍采用 Lσ=(1−K)Lp；它不是新矩阵中的 kij。启用矩阵后旧 K 隐藏，不额外叠加一份串联漏感。')
    doc.add_heading('16.2  周期电流与输出直流电压',2)
    equation(doc,'Rload_j = V_j,est²/Prated_j')
    equation(doc,'Iavg_j = Vo_j/Rload_j')
    equation(doc,'Pactual_j = Vo_j²/Rload_j')
    if symbols:
        symbols(
            ('Rload_j','第 j 路在所选负载档位使用的恒阻负载','Ω'),
            ('V_j,est，Vo_j','含规定压降的端口参考电压及实际求解的端口直流电压','V'),
            ('Prated_j，Pactual_j','用于换算电阻的功率设定值及该电阻的实际功耗','W'),
            ('Iavg_j','第 j 路端口平均负载电流','A'),
        )
    paragraph(doc,'按开关、整流二极管及钳位支路的导通状态，对每个线性 RL 区间求解矩阵方程，再求电流归零等换流事件。优化未知的周期初始电流、非反馈输出直流电压及占空比，使电流周期连续并满足每路平均电荷平衡。主反馈电容端固定在需求端口电压加防反管压降。由参考电压和功率换算出的负载电阻在求解中固定。')
    paragraph(doc,'各绕组按自身等效铜线长度和总裸铜截面积计算 DCR。自动线径先按标称 RMS 与目标电流密度确定。冻结线径、匝数、绕组结构和 DCR 后，周期求解用实际 RMS 计算电流密度与铜损。调整层序、绝缘、线径、匝数或已建模的路径后重新建立硬件。')
    paragraph(doc,'电路还包含 MOS 导通电阻、采样电阻、整流固定压降和相对输入母线的理想定压钳位。预设效率仅用于提供初值。局部 DCM 指副边在退磁能量传递区间内提前截止。判定只查看这段退磁区间。')
    paragraph(doc,'求解检查周期电流残差、各路平均电荷与能量平衡；未收敛则拒绝输出结果，不回退成看似正常的旧波形。输出电容在直流求解中视为刚性电压，随后使用已平衡电流重建纹波及频带 RMS。纹波超过输出电压 10% 时提示不适用小纹波近似。未计算完整电容启动、反馈环路瞬态及空载寄生泄放；各路额定功率需大于零。')
    doc.add_heading('16.3  钳位尖峰与损耗',2)
    equation(doc,'Vds,plateau = Vinbus + Vr')
    equation(doc,'Vds,clamp = Vinbus + Vc')
    equation(doc,'treset ≈ Lσ·Ioff/(Vc−Vr)')
    equation(doc,'Prcd = fs·∫_0^Ts(Vc·iclamp)dt')
    equation(doc,'Rsnub = Vc²/Prcd')
    equation(doc,'Csnub ≈ Prcd/(fs·Vc·ΔVc)')
    if symbols:
        symbols(
            ('Vds,plateau，Vds,clamp','MOS 漏源电压的关断平台值和理想钳位值','V'),
            ('Vinbus，Vr，Vc，ΔVc','输入防反后母线电压、反射电压、相对母线的钳位电压及容许钳位纹波','V'),
            ('treset，Lσ，Ioff','快速模型中漏感复位时间、等效漏感和关断时原边电流','s；H；A'),
            ('iclamp，Ts，fs','流入钳位支路的电流、开关周期及开关频率','A；s；Hz'),
            ('Prcd，Rsnub，Csnub','RCD 支路平均耗散、钳位电阻及钳位电容初选值','W；Ω；F'),
        )
    paragraph(doc,'矩阵模式的尖峰及持续区间来自原边钳位换流，钳位功耗由支路积分得到。钳位接回 Vin 母线，关断换流电流在该局部回路循环，不再额外当成外部输入电源电流。波形、耐压应力、钳位功耗与 R/C 初选使用同一结果，不再增加旧漏感能量估算。')
    paragraph(doc,'关闭矩阵时，快速模型采用漏感与恒定 Coss 的首波包络及恒压钳位，达到钳位后用电感压差估算复位时间；能量不足以达到钳位时只显示首波，钳位功耗为零。无漏感不虚构尖峰。物理包络峰值与 Kc 定义的钳位应力上限分开列出；反激不再叠加振铃裕度，仍须核对实际器件额定值和降额。')
    paragraph(doc,'MOS 栅电荷法 t1–t8 的公式和时长保持不变。开通从关断平台开始，关断图加入同一钳位过程；超过 t8 的钳位恢复单独显示，不拉长 t7/t8。交叠与 Coss 损耗仍为峰值电压下的保守工程估算，未对真实开关边沿进行联合求解。')
    doc.add_heading('16.4  模型边界与验证',2)
    paragraph(doc,'本模型不含非线性 Coss、二极管结电容、反向恢复、布线和绕组电容造成的振铃，不能预测极窄寄生过冲。通用完整电感矩阵也不能唯一分离公共磁芯与漏磁通；磁件 B 和磁芯损耗采用原边磁链参考，不作为实物饱和认证。周期电路只使用几何 DCR；损耗统计在同一电阻上增加交流电阻系数估计，不重复加入已积分的直流铜损。旧 JSON 的 coupling_config.dcr 不再控制工作电阻。')
    paragraph(doc,'小信号不复用旧功率比例 Bode。新环路工具在已收敛的周期解附近微扰，保留副边初值与各路电容状态，计算低频局部响应和唯一主反馈回路；说明见多路输出环路章节。各输出直流偏差仅反映当前负载点；完整交叉调整率仍需独立负载扫描并与 SPICE 或实测对标。')
    paragraph(doc,'原厂参考：Texas Instruments，Synchronous rectifiers improve cross-regulation in flyback power supplies。文中描述漏感换流电压抬升、轻载路峰值充电及整流电流提前截止。')
    paragraph(doc,'https://www.ti.com/document-viewer/lit/html/SSZTD98/GUID-56A31413-780F-4984-B393-18DC28330328',True)
    paragraph(doc,'Analog Devices，Using Transformers in LTspice SwitcherCAD III。说明多绕组需要全部成对耦合、物理可实现性检查及寄生瞬态建模边界。')
    paragraph(doc,'https://www.analog.com/en/resources/technical-articles/using-transformers-in-ltspice-switcher-cadiii.html',True)


def add_coupling_snapshot(doc, op):
    section(doc,'1.2  绕组耦合计算快照')
    meta=op['coupled_model']
    if meta.get('ideal_fallback'):
        paragraph(doc,'全部 kij=1：采用原理想变压器标称分配。没有非理想绕组电流的唯一解，不把该回退结果称为逐路物理预测。')
    else:
        paragraph(doc,'本次采用逐对耦合周期电路解。求解值与目标值分开列示；环路须使用该周期解的低频线性化，不能沿用旧功率比例模型的 Bode。结果与近似条件见环路章节；临时低频带宽限制已停用。')
    labels=meta['labels']
    table(doc,['绕组']+labels,[(label,)+tuple(f'{x:.7g}' for x in row)
                              for label,row in zip(labels,meta['K'])])
    table(doc,['绕组','自感','DCR','匝比来源'],[(label,f"{meta['L'][i][i]*1e6:.5g} µH",
        f"{meta['R'][i]*1e3:.5g} mΩ",meta['ratio_sources'][i]) for i,label in enumerate(labels)],
        [1.,1.8,1.5,2.8])
    if not meta.get('ideal_fallback'):
        table(doc,['求解检查','结果'],[
            ('最大归一化周期与电荷残差',f"{meta['normalized_residual']:.4g}"),
            ('能量平衡残差',f"{meta['energy_balance_W']:.4g} W"),
            ('钳位支路功耗',f"{meta['P_rcd']:.5g} W"),
            ('各路实际端口电压（防反后）',' / '.join(f'{v:.5g} V' for v in meta['output_voltages'])),
            ('各路电容端电压（防反前）',' / '.join(f'{v:.5g} V' for v in meta.get('capacitor_voltages',meta['output_voltages']))),
            ('输入防反功耗',f"{meta.get('P_input_blocking',0):.5g} W"),
            ('各路输出防反功耗',' / '.join(f'{v:.5g} W' for v in meta.get('P_output_blocking',[])))])
    for note in meta['assumptions']:
        paragraph(doc,note,True)
