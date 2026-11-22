"""Editable LLC calculation chapter and control figures."""

from docx_layout import equation, figure, paragraph, section, table
from docs.calculation_reference_layout import add_symbols
from docs.llc_control_diagrams import render_llc_control
from llc_settings import HYBRID_MODE, VOLTAGE_MODE
import word_math as wm


def add_llc_chapter(doc):
    aliases = ('L_r', 'L_m', 'N_p', 'N_s', 'C_r', 'f_r', 'f_m', 'R_ac', 'R_load', 'R_tank',
               'V_b', 'i_r', 'i_m', 'i_rect', 'v_d', 'v_Cr', 'v_p', 'v_cap', 'v_o',
               'R_s', 'R_d', 'V_f', 'V_block', 'Z_r', 'Z_p', 'V_o', 'P_o', 'i_k',
               'v_k', 'R_k', 'C_k', 'Q_comm', 'Q_oss', 'C_eq', 'A_e', 'T_h', 'f_s',
               'f_min', 'f_max', 'u_f', 'u_h', 'V_set', 'V_fb', 'f_bias', 'k_s',
               'm_s', 't_d', 'g_h', 'σ_h', 'B_T', 'B_L', 'N_L', 'V_inj', 'V_out,ac')
    wm.ALIASES.update({name: name for name in aliases})
    wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)

    def P(text):
        paragraph(doc, text)

    def E(text, numerator=None, denominator=None):
        equation(doc, text, numerator, denominator)

    def H(title):
        doc.add_heading(title, 2)

    section(doc, '22  LLC 谐振变换器与混合滞环控制')
    P('LLC 用两个电感和一个串联电容传递能量。原边可选半桥或全桥，副边采用单路全桥整流。'
      '从基波近似初选谐振腔，再用逐段周期解计算稳压工作点、波形和器件应力。'
      '同一个周期模型可接电压变频或混合滞环控制，并在相同工作点与 LTspice 开关波形对照。')

    H('22.1  激励、折算与元件初选')
    P('所有谐振量折算到变压器原边。半桥输出去除直流偏置后，差模激励为正负半母线电压。'
      '全桥两桥臂反向驱动，差模激励为正负整母线电压。半桥 Cr 耐压应计入半母线电压偏置。'
      '电压取样在输出防反器件前的电容端，负载接在防反器件后的端口。')
    E('n = N_p/N_s；R_load = V_o²/P_o')
    E('f_r = 1/(2π√(L_r·C_r))；f_m = 1/(2π√((L_r+L_m)·C_r))')
    E('R_ac = 8·n²·R_load/π²；Z_r = √(L_r/C_r)；Q = Z_r/R_ac')
    add_symbols(doc,
        ('N_p、N_s、n', '原副边整数匝数与匝比', '匝、匝、1'),
        ('V_o、P_o、R_load', '额定端口电压、功率及恒阻负载', 'V、W、Ω'),
        ('L_r、C_r、L_m', '总串联谐振电感、谐振电容和励磁电感。折算漏感计入电感一次', 'H、F、H'),
        ('f_r、f_m', '串联谐振频率和整流截止时的低端谐振频率', 'Hz'),
        ('R_ac、Z_r、Q', '基波折算负载、特征阻抗与折算品质因数', 'Ω、Ω、1'))
    P('取 s=j2πf，用励磁电抗与折算负载并联得到 Zp。串联电阻 Rtank 汇集谐振支路的等效铜阻和电容 ESR。'
      '把桥方波用基波代替，通过阻抗分压求增益。低线满载核对能否升至目标电压，高线轻载核对频率上限。')
    E('Z_p = (s·L_m·R_ac)/(s·L_m+R_ac)')
    E('M(f) = |Z_p/(R_tank+s·L_r+1/(s·C_r)+Z_p)|')

    H('22.2  谐振腔逐段模型与周期求解')
    P('谐振电流 ir 从桥流向变压器，励磁电流 im 流入励磁支路。vCr 为去直流偏置的电容电压，'
      'vd 为差模激励，vp 为原边点端相对非点端电压。串联通路电阻 Rs 按相应导通状态叠加 MOS 电阻。')
    E('L_r·d(i_r)/dt = v_d-v_Cr-R_s·i_r-v_p')
    E('C_r·d(v_Cr)/dt = i_r；L_m·d(i_m)/dt = v_p')
    P('副边整流桥每次有一对二极管串联。用 σ=±1 表示导通对的极性。单颗二极管以正向门槛 Vf 和斜率电阻 Rd 表示。'
      '流入整流桥的原边折算电流为 ir−im。截止区两电流相等，原边电压由 Lr 与 Lm 串联分压。')
    E('v_p = σ·n·(v_cap+2V_f)+2n²·R_d·(i_r-i_m)；i_rect = n·σ·(i_r-i_m)')
    E('v_p = (L_m/(L_r+L_m))·(v_d-v_Cr-R_s·i_r)')
    P('每颗输出电容保留内部电压 vk 和支路电流 ik。支路 Ck、Rk 使用实际容量与 ESR。'
      '整流汇流与电容充电、负载消耗共同满足节点电流平衡。Vblock 为启用时的固定防反压降。')
    E('v_cap = v_k+R_k·i_k；C_k·d(v_k)/dt = i_k')
    E('i_rect = v_o/R_load+∑_k (i_k)；v_o = v_cap-V_block')
    P('在每个开关事件与整流换流之间积分。以正半周期开始为采样点，要求结束时的 ir、vCr、im 分别变号，'
      '电容组内部电压回到原值。先解此周期状态，再改变开关频率，让端口平均电压达到设定值。'
      '优先选下降增益支路上的较高频工作点。报告保留限频、保护和周期未收敛标记。')

    H('22.3  死区电荷、磁链与损耗')
    P('死区开始于上一组 MOS 关断。以单颗 MOS 的等效换流电容为基准，半桥桥臂等效为两颗并联，'
      '全桥两臂差模等效为单颗。指定 Qoss 时，以该端点的母线电压折算等效电容。'
      '桥节点达到母线轨后由体二极管钳位。按开通前的残余漏源电压和死区内有向换流电荷判读 ZVS。')
    E('C_eq = Q_oss/V_b；Q_comm = 2Q_oss')
    P('上式 Ceq 为单颗等效电容（F），Qoss 为单颗在母线电压 Vb 下的换流电荷（C），Qcomm 对应该次桥换向的理论电荷（C）。'
      '若没有 Qoss，按器件配置的常数 Coss 仿真。软开关判据还要核对死区结束时真实桥节点是否到达目标电位。')
    E('B_T = L_m·i_m/(N_p·A_e)；B_L = L_r·i_r/(N_L·A_e)')
    P('BT、BL 为按各自磁芯和匝数换算的瞬时磁密（T）。Ae 为相应的有效截面积（m²），NL 为谐振电感匝数。'
      '以磁密周期曲线计算 NSE 磁损。效率账本汇总原边导通、开通残压、门极驱动、副边导通、谐振串联电阻、'
      '磁芯及输入输出电容组损耗。绕组铜阻已纳入串联支路时按一次计损。')

    H('22.4  两种控制与低频线性化')
    P('两种控制读取同一防反前取样端，以参考电压与取样电压之差驱动 PI。电压变频将控制量变成频率下降量，'
      '振荡器决定半周期，互补时序负责桥臂极性和死区。')
    E('e = V_set-V_fb；u_f(s) = (Kp+Ki/s)·e(s)；f_s = f_bias-u_f')
    figure(doc, render_llc_control(VOLTAGE_MODE).getvalue(),
           '图 22-1  LLC 电压变频控制的反馈、限频与桥臂时序', width=14.8/2.54)
    P('Vset、Vfb 和误差 e 的单位为 V。uf 为降频指令（Hz），Kp 与 Ki 分别用 Hz/V 和 Hz/(V·s)。'
      '频率被钳在 fmin 至 fmax 之间，空载突发与保护停脉冲需单独分析。')
    P('混合滞环（HHC）以 PI 输出阈值。半周期极性翻转谐振电容的交流采样，每一半周叠加正向补偿斜坡。'
      '计时从上一对 MOS 关断开始，斜坡在死区结束后起算。频率上限给出可比较的最短时间，频率下限给出强制换向的最长时间。')
    E('g_h(t) = k_s·σ_h·v_Cr(t)+m_s·max(0,t-t_d)')
    E('g_h(T_h) = u_h；1/(2f_max) ≤ T_h ≤ 1/(2f_min)')
    figure(doc, render_llc_control(HYBRID_MODE).getvalue(),
           '图 22-2  LLC 混合滞环的电容取样、斜坡、阈值与关断时序', width=14.8/2.54)
    P('ks 是电容采样比（1），σh 是桥驱动的半周极性（±1），ms 是补偿斜率（V/s），td 为死区（s），Th 是半周期（s）。'
      '比较量 gh 和等效阈值 uh 用 V。HHC 的 Kp 用 V/V、Ki 用 1/s。'
      '稳态使用满足规定比较窗口的首次上穿，比较斜率不足或触及限频时保留工作区提示。')
    P('围绕周期解中心差分，以频率下降量或滞环阈值作为第一个输入，端口额外抽走的负载电流（A）作为第二个输入。'
      '将换向后的状态和半周期平均电压分别记作 x⁺ 与 y，得到周期映射雅可比矩阵。')
    E('Δx⁺ = A·Δx+B·Δu；Δy = C·Δx+D·Δu')
    E('s = (2/T_h)·(z-1)/(z+1)')
    P('x 包含谐振电流、电容电压、励磁电流及输出各支路电压。u 是控制量和负载扰动，y 为平均端口电压。'
      'A、B、C、D 是上述偏导矩阵。双线性变换用于低频 Bode 和负载阶跃。'
      '平均模型的扫频上限是实际开关频率的十分之一，目标穿越频率至多为实际频率的三十分之一。'
      '固定点失稳、限频、限流和整流工作区跃迁须结合开关级验证。')

    H('22.5  两端点对照方法与 300 W 半桥算例')
    P('在示例选择半桥混合滞环，输入 360–420 V，输出 48 V／6.25 A。取 Np:Ns=24:6，'
      'Lr=50 µH，Cr=50.66 nF，Lm=250 µH，死区 250 ns。由式（22-1）至（22-3）得 '
      'Rload=7.68 Ω，Rac=99.60 Ω，fr 约 100 kHz，fm 约 40.8 kHz，Q 约 0.315。'
      '两个输入端点共用同一组 PI。开关结果按满载收敛后整数周期统计，取样端、方向和有效值口径与计算对齐。')
    E('T = -V_out,ac/(V_inj+V_out,ac)')
    P('频响分析（FRA）按加到反馈取样的正弦电压 Vinj 和同频输出 Vout,ac 的复数基波量（V），'
      '反求无量纲回路增益 T。')
    caption = doc.add_paragraph('表 22-1  半桥混合滞环计算与 LTspice 对照', 'Caption')
    caption.paragraph_format.keep_with_next = True
    table(doc, ['项目', '360 V 计算 / 仿真', '420 V 计算 / 仿真'], [
        ('端口平均电压 / V', '48.000 / 48.000', '48.000 / 48.000'),
        ('开关频率 / kHz', '85.151 / 84.993', '113.607 / 114.371'),
        ('谐振电流 RMS / A', '2.343 / 2.329', '2.172 / 2.115'),
        ('700 Hz 开环幅值 / dB', '0.00 / +0.52', '+2.96 / +3.14'),
        ('700 Hz 开环相位 / °', '−115.0 / −114.0', '−112.0 / −111.5'),
    ], [2.55, 2.23, 2.23])
    P('输出电容组为 3 × 470 µF 与 4.7 µF 薄膜旁路。'
      '按 0.10 V 与 0.05 V 两档注入在 700 Hz 复核同频响应。'
      '开关仿真双向阶跃的最大跌落为 0.54 V／0.45 V，最大过冲为 0.50 V／0.38 V。'
      '启动的 Coss 位移电流、谐振电流和完整周期 RMS 分别记录。'
      '周期模型用线性器件，开关仿真可带结电容和 ESL。实物的非线性 Coss、磁芯饱和、突发模式及温度另行核对。')
    doc.add_paragraph('基波近似与设计初选见 Infineon AN 2012-09 与 TI SSZTCH0。'
                      'HHC 阈值和斜坡结构见 TI UCC25640x §7.3.1 与 SLUAAJ7 §2.4。'
                      '本章方程和数值对应软件实现的通用可配置行为模型。', 'Reference Note')
    doc.add_paragraph('https://www.ti.com/lit/ds/symlink/ucc256403.pdf  ·  https://www.ti.com/lit/an/sluaaj7/sluaaj7.pdf',
                      'Reference Note')
