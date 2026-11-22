"""COT chapter of the editable calculation reference."""

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor

from docx_layout import equation, paragraph, section, table
from docs.calculation_reference_layout import add_symbols
import word_math as wm


def add_cot_chapter(d, add_control_figure):
    wm.ALIASES.update({name: name for name in (
        'f_target', 'f_s', 'T_s', 'T_on', 'T_off',
        'T_on,0', 'T_on,j', 'T_off,min', 'V_in,a', 'V_up', 'V_dn', 'V_Δ',
        'V_Δ,j', 'V_cap', 'V_b', 'V_sw,q,j', 'R_eq', 'L_eq', 'R_avg',
        'R_avg,j', 'R_h', 'R_h,j', 'R_l', 'R_l,j', 'R_s', 'R_dc', 'R_dc,j',
        'R_src', 'R_load', 'K_bal', 'K_if', 'k_t,j', 'a_j', 'b_j', 'D_j',
        'D_bal,j', 'I_m,j', 'I_m,avg', 'I_φ', 'I_φ,pk', 'I_φ,rms',
        'I_φ,min', 'I_j', 'ΔI_φ', 'ΔI_Σ', 'Δi_j', 'Δi_k', 'Δi_m,j',
        'Δi_m,avg', 'Δi_o', 'Δi_f', 'Δf_cmd', 'ΔD_j', 'ΔD_bal,j', 'Δv_k',
        'Δv_cap', 'ESR_k', 'ESL_k', 'C_k', 'Z_k', 'Z_o', 'G_vf', 'V_set',
        'τ_bal', 'τ_if', 't_dead', 'ΔV_dead,j', 'θ_PI', 'M_PI', 'PM_target',
        'D_u', 'S_up', 'S_dn', 'Q_up', 'Q_dn', 't_d', 'R_ESR', 'ΔI_step',
        'ΔV_lim', 'C_min',
    )})
    wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)

    def P(text):
        paragraph(d, text)

    def H(text):
        d.add_heading(text, 2)

    def E(text):
        equation(d, text)

    section(d, '21  同步 Buck 的 COT 控制与建模')
    P('本章从电感伏秒平衡和交错时序求稳态，随后在同一工作点建立频率指令到输出电压的平均小信号模型。'
      '适用于软件的 1–16 相同步 Buck，各相有独立高低侧 MOSFET 和电感，共用输入母线与单一输出。')
    P('电感电流以开关节点流向输出为正。负载电流和功率在输出端口统计，反馈在输出防反器件前的电容节点取样。'
      '采用固定防反压降时，两个节点的电压增量相同。输入也区分连接器、输入防反后和源串联阻抗后的母线。')

    H('21.1  导通定时与相同支路的伏秒平衡')
    P('COT（Constant On-Time，恒定导通时间）每触发一次就按定时产生一个高侧脉冲。软件可录入固定脉宽，'
      '也可用输入前馈计算脉宽。负反馈通过改变触发间隔调节能量。自适应模式以目标频率计算定时，实际频率由工作点确定。')
    E('T_on,0 = V_cap/(V_b·f_target)')
    E('f_s = D/T_on；T_off = (1-D)/f_s')
    add_symbols(d,
        ('V_b、V_cap', '源串联压降后的母线电压、反馈电容端稳态电压', 'V'),
        ('f_target、f_s', '每相目标开关频率、由稳态求得的每相实际开关频率', 'Hz'),
        ('T_on,0、T_on、T_off', '基准导通时间、高侧导通时间、剩余关断时间', 's'),
        ('D', '高侧导通时间与每相周期之比', '1'),
    )
    P('先取相同的功率支路和均匀分流，并忽略死区及附加源电阻。负载总电流为 Iₒ=Pₒ/Vₒ，每相平均电流 Iφ=Iₒ/N。'
      '高侧导通时，电感电压为正值 Vup。低侧导通时为负值，其幅值记作 Vdn。')
    E('V_up = V_b - V_cap - I_φ·(R_h+R_s+R_dc)')
    E('V_dn = V_cap + I_φ·(R_l+R_dc)')
    E('D·V_up = (1-D)·V_dn；D = V_dn/(V_up+V_dn)')
    E('ΔI_φ = V_up·T_on/L；I_φ,pk = I_φ + ΔI_φ/2')
    E('I_φ,min = I_φ - ΔI_φ/2；I_φ,rms = √(I_φ²+ΔI_φ²/12)')
    add_symbols(d,
        ('Pₒ、Vₒ、Iₒ', '输出端口功率、稳态端口电压、流向负载的平均电流', 'W、V、A'),
        ('N、L', '活动相数、每相电感', '1、H'),
        ('R_h、R_l、R_s、R_dc', '高侧和低侧导通电阻、高侧路径采样电阻、电感直流电阻', 'Ω'),
        ('ΔI_φ、I_φ,pk、I_φ,min、I_φ,rms', '单相电感电流峰峰值、峰值、谷值及整周期有效值', 'A'),
    )
    P('若上升或下降斜率失去余量，或者 T_off 小于设置的最小关断时间 T_off,min，该点无法按上述时序达到规定输出。'
      '强制同步允许负谷值。启用二极管仿真后，达到零电流时实际导通状态发生变化。')

    H('21.2  交错纹波与非均匀分流')
    P('相同支路的触发起点以每相周期 Tₛ=1/fₛ 的 1/N 错开。一个交错间隔内，高侧同时导通的相数在 '
      'floor(ND) 和 floor(ND)+1 之间切换。令 a 为 ND 的小数部分，后一种状态持续 aTₛ/N。'
      '合成电流在此段的上升斜率为 (1−a)(Vup+Vdn)/L，两者相乘得到峰峰值。')
    E('a = N·D - floor(N·D)；ΔI_Σ = (V_up+V_dn)·T_s·a·(1-a)/(N·L)')
    P('a 无量纲，floor 表示向下取整，ΔIΣ 单位为 A。相同支路在 ND 为整数时，理想合成纹波可抵消。'
      '失配时仍按 Tₛ/N 交错起始，计算器在每个脉冲起止断点求合成电流极值。输出电容的电荷纹波'
      '取合成电流减去负载电流后的积分，并检查相邻断点之间的零电流点。各相失配会使频谱出现每相频率分量。')
    P('增强计算给每相配置 L、DCR、开关导通电阻、定时倍率以及采样增益和偏置。均流环比较各相采样值与采样平均值。'
      '低采样相获得正占空比修正，高采样相获得负修正，修改后的占空比再进入伏秒方程。')
    E('I_m,j = a_j·I_j + b_j；I_m,avg = (∑_j I_m,j)/N')
    E('D_bal,j = clip(K_bal·(I_m,avg-I_m,j)/V_b)')
    E('D_j = f_s·T_on,0·k_t,j + D_bal,j；T_on,j = D_j/f_s')
    E('∑_j I_j = Pout/Vout；V_b = V_in,a - R_src·(∑_j D_j·I_j)')
    add_symbols(d,
        ('j、Ij、Im,j、Im,avg', '相索引、相平均电流、该相采样量及所有相的采样平均值', '1、A、A、A'),
        ('aj、bj、kt,j', '该相的电流采样倍率、采样偏置、导通定时倍率', '1、A、1'),
        ('Kbal、Dbal,j、Dj', '均流增益、该相占空比修正、该相实际占空比', 'V/A、1、1'),
        ('Vin,a、Rsrc', '输入防反后的源电压、母线前串联电阻。clip 按所设绝对占空比限值对称截幅', 'V、Ω'),
    )
    P('各相分别写一周期伏秒为零。程序同时求公共频率、母线电压和各相电流。'
      '有死区时，两段死区电压分别由电流谷值与峰值的方向确定。每段死区占一个周期的比例为 tdead·fₛ。'
      '连续导通近似波形仍以这组平均工作点构造。')
    E('V_Δ,j = V_b - I_j·(R_h,j-R_l,j)')
    E('0 = D_j·V_Δ,j - V_cap - I_j·(R_l,j+R_dc,j) + ΔV_dead,j')
    E('ΔV_dead,j = t_dead·f_s·(∑_q (V_sw,q,j+I_j·R_l,j))')
    P('上式的 Rh,j 包含该相高侧路径及采样电阻，Rl,j 为低侧导通电阻，Rdc,j 为电感 DCR。'
      'VΔ,j 是占空比增量的等效电压系数。q 取每周期的两个死区，Vsw,q,j 是该死区内的开关节点电压。'
      '正电流经低侧体二极管续流，节点为负的正向压降。负电流经高侧体二极管续流，节点为母线电压加正向压降。'
      '两次修正以低侧导通状态为起点，得到平均电感电压，所有电压量以 V 计，tdead 以 s 计。')

    H('21.3  频率 PI 与等效功率级')
    P('频率 PI 模型以归一化电压误差调节每相触发频率。设定值固定时，反馈电压升高会使频率指令下降。'
      '在线性化中先冻结输入母线及稳态脉宽，令占空比小扰动等于脉宽乘以触发频率小扰动。')
    add_control_figure(d, 'cot_frequency_pi', 'COT 频率 PI 的信号路径',
                       '电容端电压与设定值求差，经频率 PI、相序触发和导通定时驱动 Buck，各相汇入输出并返回电压取样。')
    E('ΔD = T_on·Δf_cmd；R_avg = D·(R_h+R_s)+(1-D)·R_l+R_dc')
    E('L_eq = L/N；R_eq = R_avg/N；V_Δ = V_b-I_φ·(R_h+R_s-R_l)')
    E('Z_k(s) = ESR_k+s·ESL_k+1/(s·C_k)；Z_o(s) = 1/(1/R_load+∑_k (1/(Z_k(s))))')
    E('G_vf(s) = (T_on·V_Δ·Z_o(s))/(s·L_eq+R_eq+Z_o(s))')
    E('T(s) = G_vf(s)·(Kp+Ki/s)/V_set')
    P('Δf_cmd 为每相的频率指令增量（Hz）。Ravg、Leq、Req 分别为单相平均导通电阻、合成支路等效电感和电阻。'
      '式中只激励各相的共模电流，等效支路电压源为 VΔ·ΔD。由该源在 sLeq+Req 与 Zo 间的分压，得到 Gvf（V/Hz）。')
    P('k 为输出电容索引，Ck、ESRk、ESLk 分别用 F、Ω、H 表示。Rload 是端口等效阻性负载。'
      'Zk 与 Zo 是支路和负载并联网络的阻抗（Ω）。每颗电容计入 ESR，ESL 按设置启用。'
      'Vset 为工作点采用的电容端设定值（V）。软件的 Kp、Ki 分别以 Hz、Hz/s 表示，T 为无量纲环路增益，s 为拉普拉斯变量（s⁻¹）。')

    H('21.4  总电流反馈与逐相平均状态方程')
    P('增强模型将各相电流分别列为状态，以保留相间偏差和均流动态。电压 PI 输出频率指令，'
      '总采样电流的滤波增量形成全相共用的快速负反馈。由各相采样差形成的均流修正经另一滤波器进入各相占空比。'
      '使用频率 PI 且启用了失配或均流时，也可保留各相状态，此时总电流负反馈项取零。')
    add_control_figure(d, 'cot_current_feedback', '总电流反馈 COT 的信号路径',
                       '各相电流采样分别汇入总电流滤波和均流比较，前者从公共频率指令扣除，后者逐相修正占空比。')
    E('Δi_m,j = a_j·Δi_j；Δi_m,avg = (∑_j Δi_m,j)/N')
    E('τ_if·d(Δi_f)/dt + Δi_f = ∑_j Δi_m,j')
    E('τ_bal·d(ΔD_bal,j)/dt + ΔD_bal,j = K_bal·(Δi_m,avg-Δi_m,j)/V_b')
    E('ΔD_j = T_on,0·k_t,j·(Δf_cmd-K_if·Δi_f)+ΔD_bal,j')
    P('Δ 是围绕工作点的增量。Δij 是相电感电流增量，Δim,j 是采样增量，Δif 是各相采样电流相加后的滤波增量（A）。'
      '采样偏置保持为常量，已反映在直流工作点。τif=1/(2πfif) 和 τbal=1/(2πfbal) 分别为总电流滤波、'
      '均流滤波的时间常数（s）。Kif 为总电流反馈增益（Hz/A）。若某相均流已达到占空比修正限值，'
      '该相均流滤波项的输入增益在当前线性化点取零。')
    P('把伏秒方程在工作点展开，保留电感电流、受控占空比和电容端电压的一阶项。'
      '此平均计算把死区及源阻抗的直流影响带入工作点，输入 R/L/C 动态与详细死区换流留给开关模型。')
    E('R_avg,j = D_j·R_h,j+(1-D_j)·R_l,j+R_dc,j')
    E('L_j·d(Δi_j)/dt = V_Δ,j·ΔD_j - R_avg,j·Δi_j - Δv_cap')
    P('Lj 为第 j 相电感（H），Ravg,j 为该相的平均导通电阻（Ω），Δvcap 为电容端电压增量（V）。'
      '在输出节点，来自所有电感的电流流向负载和各电容支路。电容电流以流入支路为正，'
      '将额外取走的负载电流 Δio（A）作为独立正向扰动。')
    E('∑_j Δi_j = Δv_cap/R_load + Δi_o + ∑_k Δi_k')
    E('C_k·d(Δv_k)/dt = Δi_k')
    E('ESL_k·d(Δi_k)/dt + ESR_k·Δi_k + Δv_k = Δv_cap')
    P('Δik 是第 k 颗电容支路电流增量（A），Δvk 是理想电容两端电压增量（V）。启用 ESL 时，其支路电流也列为状态。'
      '未启用 ESL 时，从节点方程代入支路的代数电流关系。恒流负载的小信号电导近似为零。'
      '若恒流负载与全部含 ESL 的电容支路同时使用，理想电流阶跃可产生电压冲激，软件对该阶跃单独提示适用限制。')
    P('由以上各式消去节点代数量，把电感、电容和各滤波状态写入列向量 x。'
      '暂取 Δio=0，得到以 Δf_cmd 为输入、Δvcap 为输出的连续状态空间。')
    E('dx/dt = A·x+B·Δf_cmd；Δv_cap = C·x+D_u·Δf_cmd')
    E('G_vf(s) = C·(s·I-A)^(-1)·B+D_u')
    P('A、B、C 由上一组状态方程和输出节点约束确定，I 为与 A 同阶的单位矩阵。'
      'Dᵤ 为频率指令到输出电压的直接馈通项，对该输入取零。Gvf(s) 仍用 V/Hz，与归一化 PI 相乘得 T(s)。'
      '计算闭环负载响应时再接入 Δio，'
      '输出变化由同一组电容、均流和电流反馈状态共同决定。')

    H('21.5  判读频带与动态校核')
    P('自动整定先用目标穿越频率 fc 和相位裕度 PMtarget 确定频率 PI 应补足的相角 θPI、以及使环路达到单位增益的幅值 MPI。'
      '由于 PI 在该频率的值为 Kp−jKi/ωc，实部和虚部分别给出两项增益。')
    E('θ_PI = PM_target - 180° - arg(G_vf(j·ωc))')
    E('M_PI = V_set/|G_vf(j·ωc)|；Kp = M_PI·cos(θ_PI)；Ki = -ωc·M_PI·sin(θ_PI)')
    P('ωc=2πfc 为目标角频率（rad/s），j 为虚数单位，arg 取展开的相位角（°），MPI 的单位为 Hz。'
      '有效 PI 相角为 −90° 至 0°（不含 0°）。整定回填同一组 PI，输入两端分别复算，以各自工作点读图。')
    P('自动整定目标穿越频率至多为实际每相频率 fₛ/20，平均 Bode 扫描至 fₛ/10。'
      '相位裕度在 0 dB 向下穿越处读取。增益裕度需要扫描频带内出现 −180° 相位交越。'
      '若该交越未落在扫描内，增益裕度标为未覆盖。')
    P('平均模型用于活动相数固定、连续电流和工作点未进入限流或最小关断时间限幅的条件。'
      '轻载减相、死区换流、详细取样与纹波注入、启停时序和逐周期保护应按相应的开关模型或实物证据评估。'
      '电荷法用于输出电容初筛，闭环平均阶跃用于检查反馈速度与阻尼，大信号开关波形用于核对限流和脉冲约束。')
    P('电荷初筛把负载突变后的电流差近似为矩形与三角形面积之和。延迟 t_d 后，'
      '取各相电感最大爬升斜率或下降斜率之和 S_up、S_dn。增载形成电荷亏缺 Q_up，减载形成电荷剩余 Q_dn。')
    E('Q_up = ΔI_step·t_d + ΔI_step²/(2·S_up)；Q_dn = ΔI_step·t_d + ΔI_step²/(2·S_dn)')
    E('C_min = Q/(ΔV_lim-ΔI_step·R_ESR)')
    P('ΔIstep 为负载变化的幅值（A），t_d 用 s，S_up、S_dn 用 A/s，Q_up、Q_dn 用库仑。'
      '按增载或减载分别代入对应电荷 Q 和允许偏差 ΔVlim（V）。R_ESR 为电容组并联 ESR（Ω）。'
      '当扣除 ESR 瞬时压降后的预算为正，Cmin 给出总电容量的初选下限（F）。应取两种方向中较大的下限。'
      '若预算用尽，应先降低并联 ESR。随后用闭环时域和开关波形复核实际控制延迟、调节斜率及 ESL 边沿。')
    P('下列 TI 资料分别介绍总电流与关断时间调节，以及交错纹波与暂态电荷分析。'
      '本章框图、频率 PI 增益和状态方程遵循计算器的通用行为模型。')
    for label, url in (
        ('TI TPS536C7B1 数据手册 SLUSDI9 §7.6.2–7.6.3', 'https://www.ti.com/lit/ds/symlink/tps536c7.pdf'),
        ('TI 多相 Buck 设计应用报告 SLVA882B §3.2、§3.4、§5.5', 'https://www.ti.com/lit/an/slva882b/slva882b.pdf'),
    ):
        reference = d.add_paragraph(style='Reference Note')
        link = OxmlElement('w:hyperlink')
        link.set(qn('r:id'), reference.part.relate_to(url, RT.HYPERLINK, is_external=True))
        run = reference.add_run(label)
        run.underline = True
        run.font.color.rgb = RGBColor.from_string('175898')
        link.append(run._r)
        reference._p.append(link)

    H('21.6  复算四相 1.2 V / 80 A 算例')
    P('在「示例」载入「四相同步 Buck · COT · 1.2V / 80A」（96W_BUCK_COT_4PH.json）。输入 10–14 V，'
      '满载 96 W，每相目标 400 kHz，前馈定时。标称每相 0.30 µH、1.75 mΩ，16 颗输出电容各 330 µF、'
      'ESR 9 mΩ，环路 ESL 关闭。')
    P('输入源电阻 10 mΩ，死区 20 ns。两端共用 Kp=2.450332×10⁶ Hz、Ki=9.367016×10¹⁰ Hz/s。'
      '总电流反馈为 4000 Hz/A、30 kHz 低通。均流为 0.02 V/A、2 kHz 低通、修正限幅 ±0.05，逐相倍率及偏置沿用示例。')
    P('满载 96 W÷1.2 V=80 A。10 V 端点第 1 相的均流修正为 −0.000220，D₁≈0.13172。'
      '将上升电压 8.55584 V、导通时间 302.69 ns 和 L₁=0.30 µH×0.95 代入式（21-6），'
      '纹波为 9.087 A。平均电流 19.908 A 加半幅纹波得峰值 24.451 A。')
    table(d, ['计算项目', 'Vinmin 10 V', 'Vinmax 14 V'], [
        ('源压降后的母线电压 / V', '9.89445', '13.92513'),
        ('前馈导通时间 / ns', '303.20', '215.44'),
        ('实际每相频率 / kHz', '435.161', '434.411'),
        ('第 1 相实际导通时间 / ns', '302.69', '215.08'),
        ('合成电感电流峰峰值 / A', '5.212', '6.747'),
        ('所有相的最大峰值电流 / A', '24.556', '24.753'),
        ('电压环穿越频率 / kHz', '19.997', '20.092'),
        ('相位裕度 / °', '80.00', '79.94'),
        ('增益裕度', '至 43.516 kHz 未覆盖', '至 43.441 kHz 未覆盖'),
    ], [2.95, 1.65, 1.65])
    P('同一套硬件和 PI 下，两端平均模型均得到稳定的闭环极点。可在「环路」切换输入端点复核；'
      '开关模型 FRA 采用相同输入、负载和取样节点。')
