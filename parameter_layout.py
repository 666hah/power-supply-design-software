"""Presentation-only catalogue for the power-design parameter sidebar.

Keys and their stored SI values deliberately match ``main.PARAM_SPECS``.  This
module neither imports the GUI nor changes the calculation model.  A display
factor is applied only at the UI boundary (not when saving a configuration).
"""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FieldSpec:
    label: str
    symbol: str
    unit: str
    display_factor: float = 1.0
    advanced: bool = False
    required: bool = False
    auto: bool = False
    topologies: tuple[str, ...] = ()
    enabled_by: str = ''


SECTION_ORDER = ('spec', 'curves', 'stage', 'device', 'capacitors', 'drive', 'sense', 'mag', 'ctrl')
SECTION_TITLES = {
    'spec': '① 需求与方案',
    'curves': '器件模型精度选择',
    'stage': '② 功率级与钳位',
    'device': '③ MOS 与整流器件',
    'capacitors': '④ 输入/输出电容与防反',
    'drive': '⑤ 栅极驱动',
    'sense': '⑥ 电流采样与调制',
    'mag': '⑦ 磁件与温升',
    'ctrl': '⑧ 反馈与补偿',
}

# Non-numeric selectors (topology, controller type, core material/shape/model,
# multi-output/PSR) are placed by the GUI adjacent to these groups.  Keeping them
# out of this list preserves the numeric configuration contract.
GROUPS = {
    'curves': [],
    'spec': [
        ('电路需求', ('V_in_min', 'V_in_max', 'V_in', 'V_out', 'P_out', 'f_sw', 'eta_guess', 'ripple_target')),
        ('Buck 交错与导通时间', ('buck_phases', 'cot_ton_s', 'cot_min_off_s')),
        ('COT 电压外环 PI（两个增益均为 0 时自动）', ('cot_kp_hz', 'cot_ki_hz_per_s')),
    ],
    'stage': [
        ('储能与变比', ('L', 'N')),
        ('LLC 谐振腔', ('llc_lr', 'llc_cr', 'llc_lm', 'llc_tank_r')),
        ('有源钳位正激', ('Lm_forward', 'C_clamp', 'ESR_clamp', 'forward_d_max')),
        ('电压应力', ('ring_margin',)),
        ('旧版兼容参数', ('Vf',)),
    ],
    'device': [
        ('Q1 · 主开关 MOS', ('Rds_on', 'Coss', 'Qg', 'Vth', 'gfs', 'mos_curve_vds', 'Vgp_on', 'Vgp_off',
                           'Qg_th', 'Qgs', 'Qgd', 'Rg', 'k_sw')),
        ('D1 · 输出整流器', ('Vf_diode', 'Rd_diode', 'Qrr')),
        ('LLC 副边二极管桥', ('llc_rect_r', 'llc_diode_cj')),
        ('LLC 桥臂换流', ('llc_qoss',)),
        ('Q2 · 钳位 MOS', ('Rds_aux', 'Qg_aux', 'Coss_aux')),
    ],
    'capacitors': [
        ('输入电容 1', ('Cin1', 'Rcin1', 'ESLin1')),
        ('输入电容 2（可选）', ('Cin2', 'Rcin2', 'ESLin2')),
        ('输出电容 1', ('C_out', 'Rc', 'ESL')),
        ('输出电容 2（可选）', ('C_out2', 'Rc2', 'ESL2')),
        ('输入防反二极管（可选）', ('Vf_din', 'Rd_din')),
        ('输出防反二极管（可选）', ('Vf_dout', 'Rd_dout')),
    ],
    'drive': [
        ('驱动电压与电阻', ('Vgs', 'Rg_drive', 'Rs_on', 'Rs_off')),
        ('正激驱动时序', ('forward_dead_time',)),
        ('LLC 驱动时序', ('llc_dead_time',)),
    ],
    'sense': [
        ('电流采样', ('Rs', 'A_sense')),
        ('PWM 与斜坡补偿', ('Vm', 'ma_slope')),
        ('LLC 混合滞环检测', ('llc_hhc_sense', 'llc_hhc_ramp')),
    ],
    'mag': [
        ('成品电感参数（0=未提供）', ('inductor_dcr', 'inductor_rated_current',
                              'inductor_saturation_current', 'inductor_extra_loss')),
        ('磁密与窗口约束', ('Bmax', 'Bsat', 'Ku')),
        ('磁导率与气隙估算', ('mu_r',)),
        ('绕组与导线', ('Np', 'Ns', 'd_wire_p', 'd_wire_s', 'n_strand_p',
                      'n_strand_s', 'parallel_wires_p','parallel_wires_s')),
        ('独立谐振电感 Lr 绕制', ('llc_lr_leakage_H','llc_lr_turns','llc_lr_strands','llc_lr_wire_diameter',
                              'llc_lr_design_peak','llc_lr_min_ae','llc_lr_bobbin_radius',
                              'llc_lr_window_width','llc_lr_window_height')),
        ('散热与温升', ('Rth_transformer', 'h_conv', 'temp_rise_limit')),
        ('材料与磁芯损耗系数', ('rho', 'k_core', 'a_core', 'b_core')),
    ],
    'ctrl': [
        ('补偿器零极点', ('KP', 'fz1', 'fz2', 'fp1', 'fp2')),
        ('LLC 调频与电压环', ('llc_fmin', 'llc_fmax', 'llc_kp', 'llc_ki')),
        ('LLC 启动与保护', ('llc_soft_start', 'llc_ocp', 'llc_uvlo', 'llc_ovp')),
    ],
}

ISOLATED_TOPOLOGIES = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD', 'LLC')
FORWARD_TOPOLOGIES = ('ACF-FORWARD',)
LLC_TOPOLOGIES = ('LLC',)

META = {
    'inductor_dcr': FieldSpec('成品电感直流电阻', 'DCR', 'Ω', topologies=('BUCK','BOOST','BUCK-BOOST')),
    'inductor_rated_current': FieldSpec('厂家额定 RMS 电流', 'Irms,rated', 'A', topologies=('BUCK','BOOST','BUCK-BOOST')),
    'inductor_saturation_current': FieldSpec('厂家饱和电流', 'Isat', 'A', topologies=('BUCK','BOOST','BUCK-BOOST')),
    'inductor_extra_loss': FieldSpec('当前工况附加损耗估算', 'Pextra', 'W', topologies=('BUCK','BOOST','BUCK-BOOST')),
    'V_in': FieldSpec('输入电压', 'Vin', 'V', required=True),
    'V_in_min': FieldSpec('输入电压下限', 'Vin,min', 'V', required=True),
    'V_in_max': FieldSpec('输入电压上限', 'Vin,max', 'V', required=True),
    'V_out': FieldSpec('端口电压（防反后）', 'Vout', 'V', required=True),
    'P_out': FieldSpec('输出功率', 'Pout', 'W', required=True),
    'f_sw': FieldSpec('开关频率', 'fsw', 'Hz', required=True),
    'eta_guess': FieldSpec('预设效率', 'η预设', '%', display_factor=100, required=True),
    'ripple_target': FieldSpec('输出纹波目标', 'ΔV/Vout', '%', display_factor=100),
    'L': FieldSpec('储能电感', 'L', 'H', required=True),
    'N': FieldSpec('原副边匝比', 'Np/Ns', '', required=True, topologies=ISOLATED_TOPOLOGIES),
    'Lm_forward': FieldSpec('变压器励磁电感', 'Lm', 'H', required=True,
                            topologies=FORWARD_TOPOLOGIES),
    'C_clamp': FieldSpec('低侧钳位电容', 'Cclamp', 'F', topologies=FORWARD_TOPOLOGIES),
    'ESR_clamp': FieldSpec('钳位电容 ESR', 'ESRclamp', 'Ω', topologies=FORWARD_TOPOLOGIES),
    'forward_d_max': FieldSpec('最大占空比', 'Dmax', '%', display_factor=100,
                               topologies=FORWARD_TOPOLOGIES),
    'ring_margin': FieldSpec('MOS 电压应力裕量', 'ΔV/V', '%', display_factor=100,
                            topologies=('BUCK', 'BOOST', 'BUCK-BOOST', 'ACF-FORWARD')),
    'Vf': FieldSpec('旧版压降（不叠加损耗）', 'Vf', 'V'),
    'Rds_on': FieldSpec('导通电阻', 'Rds(on)', 'Ω', required=True),
    'Coss': FieldSpec('输出电容', 'Coss', 'F', required=True),
    'Qg': FieldSpec('总栅极电荷', 'Qg', 'C', required=True),
    'Vth': FieldSpec('典型开启阈值', 'Vgs(th)', 'V', required=True),
    'gfs': FieldSpec('有效跨导（0 固定平台）', 'gfs', 'A/V'),
    'mos_curve_vds': FieldSpec('输出曲线读取电压', 'Vds,read', 'V'),
    'Vgp_on': FieldSpec('开通平台 / Qgs参考平台', 'Vgp,ref', 'V', required=True),
    'Vgp_off': FieldSpec('手动关断米勒平台', 'Vgp,off', 'V', required=True),
    'Qg_th': FieldSpec('门限栅极电荷', 'Qg(th)', 'C', required=True),
    'Qgs': FieldSpec('零伏至米勒平台电荷', 'Qgs', 'C', required=True),
    'Qgd': FieldSpec('米勒平台电荷', 'Qgd', 'C', required=True),
    'Rg': FieldSpec('MOS 内部栅阻', 'Rg,int', 'Ω', required=True),
    'k_sw': FieldSpec('开关损耗系数', 'ksw', ''),
    'Vf_diode': FieldSpec('固定 / 换流近似压降', 'Vf', 'V', required=True),
    'Rd_diode': FieldSpec('动态电阻', 'Rd', 'Ω'),
    'Qrr': FieldSpec('反向恢复电荷', 'Qrr', 'C'),
    'Rds_aux': FieldSpec('辅助 MOS 导通电阻', 'Rds(on),Q2', 'Ω', topologies=('BUCK','ACF-FORWARD')),
    'Qg_aux': FieldSpec('辅助 MOS 总栅极电荷', 'Qg,Q2', 'C', topologies=('BUCK','ACF-FORWARD')),
    'Coss_aux': FieldSpec('辅助 MOS 输出电容', 'Coss,Q2', 'F', topologies=('BUCK','ACF-FORWARD')),
    'buck_phases': FieldSpec('并联相数', 'Nφ', '相', topologies=('BUCK',)),
    'cot_ton_s': FieldSpec('固定导通时间（0 = 自适应）', 'ton', 's', topologies=('BUCK',)),
    'cot_min_off_s': FieldSpec('最短关断时间', 'toff,min', 's', topologies=('BUCK',)),
    'cot_kp_hz': FieldSpec('比例增益', 'Kp', 'Hz', topologies=('BUCK',)),
    'cot_ki_hz_per_s': FieldSpec('积分增益', 'Ki', 'Hz/s', topologies=('BUCK',)),
    'llc_lr': FieldSpec('原边等效串联谐振电感', 'Lr', 'H', required=True, topologies=LLC_TOPOLOGIES),
    'llc_lr_leakage_H': FieldSpec('计入总 Lr 的原边漏感（0 = 待测）', 'Lσ', 'H', topologies=LLC_TOPOLOGIES),
    'llc_lr_turns': FieldSpec('绕组匝数（0 = 自动）', 'NLr', '匝', topologies=LLC_TOPOLOGIES),
    'llc_lr_strands': FieldSpec('单根绞线股数', '', '股', topologies=LLC_TOPOLOGIES),
    'llc_lr_wire_diameter': FieldSpec('裸铜单股直径（0 = 自动）', '', 'm', topologies=LLC_TOPOLOGIES),
    'llc_lr_design_peak': FieldSpec('设计校核峰值（0 = 稳态峰值）', '', 'A', topologies=LLC_TOPOLOGIES),
    'llc_lr_min_ae': FieldSpec('磁路最小截面（0 = Ae）', 'Amin', 'm²', topologies=LLC_TOPOLOGIES),
    'llc_lr_bobbin_radius': FieldSpec('骨架绕线起始半径（0 = 估算）', '', 'm', topologies=LLC_TOPOLOGIES),
    'llc_lr_window_width': FieldSpec('净窗口轴向宽度（0 = 估算）', '', 'm', topologies=LLC_TOPOLOGIES),
    'llc_lr_window_height': FieldSpec('净窗口径向深度（0 = 估算）', '', 'm', topologies=LLC_TOPOLOGIES),
    'llc_cr': FieldSpec('串联谐振电容', 'Cr', 'F', required=True, topologies=LLC_TOPOLOGIES),
    'llc_lm': FieldSpec('变压器原边励磁电感', 'Lm', 'H', required=True, topologies=LLC_TOPOLOGIES),
    'llc_tank_r': FieldSpec('原边谐振支路等效串联电阻', 'Rr', 'Ω', topologies=LLC_TOPOLOGIES),
    'llc_rect_r': FieldSpec('单只整流二极管斜率电阻', 'Rd', 'Ω', topologies=LLC_TOPOLOGIES),
    'llc_diode_cj': FieldSpec('单只整流二极管结电容', 'Cj', 'F', topologies=LLC_TOPOLOGIES),
    'llc_qoss': FieldSpec('单只 MOS 输出电荷（0 按 Coss 估算）', 'Qoss', 'C', topologies=LLC_TOPOLOGIES),
    'llc_dead_time': FieldSpec('桥臂换流死区', 'tdead', 's', topologies=LLC_TOPOLOGIES),
    'llc_hhc_sense': FieldSpec('谐振电容电压采样比例', 'As,Cr', 'V/V', required=True, topologies=LLC_TOPOLOGIES),
    'llc_hhc_ramp': FieldSpec('每半周的补偿斜坡', 'Sr', 'V/s', required=True, topologies=LLC_TOPOLOGIES),
    'llc_fmin': FieldSpec('允许最低开关频率', 'fmin', 'Hz', required=True, topologies=LLC_TOPOLOGIES),
    'llc_fmax': FieldSpec('允许最高开关频率', 'fmax', 'Hz', required=True, topologies=LLC_TOPOLOGIES),
    'llc_kp': FieldSpec('电压环比例增益', 'Kp', '', topologies=LLC_TOPOLOGIES),
    'llc_ki': FieldSpec('电压环积分增益', 'Ki', '', topologies=LLC_TOPOLOGIES),
    'llc_soft_start': FieldSpec('软启动时间', 'tss', 's', topologies=LLC_TOPOLOGIES),
    'llc_ocp': FieldSpec('谐振电流保护（0 停用）', 'Iocp', 'A', topologies=LLC_TOPOLOGIES),
    'llc_uvlo': FieldSpec('直流输入欠压（0 停用）', 'UVLO', 'V', topologies=LLC_TOPOLOGIES),
    'llc_ovp': FieldSpec('输出过压（0 停用）', 'OVP', 'V', topologies=LLC_TOPOLOGIES),
    'Cin1': FieldSpec('容量', 'Cin1', 'F', required=True),
    'Rcin1': FieldSpec('等效串联电阻', 'ESRin1', 'Ω'),
    'ESLin1': FieldSpec('等效串联电感', 'ESLin1', 'H'),
    'Cin2': FieldSpec('容量', 'Cin2', 'F', enabled_by='cin2_enable'),
    'Rcin2': FieldSpec('等效串联电阻', 'ESRin2', 'Ω', enabled_by='cin2_enable'),
    'ESLin2': FieldSpec('等效串联电感', 'ESLin2', 'H', enabled_by='cin2_enable'),
    'C_out': FieldSpec('容量', 'Cout1', 'F', required=True),
    'Rc': FieldSpec('等效串联电阻', 'ESRout1', 'Ω'),
    'ESL': FieldSpec('等效串联电感', 'ESLout1', 'H'),
    'C_out2': FieldSpec('容量', 'Cout2', 'F', enabled_by='cout2_enable'),
    'Rc2': FieldSpec('等效串联电阻', 'ESRout2', 'Ω', enabled_by='cout2_enable'),
    'ESL2': FieldSpec('等效串联电感', 'ESLout2', 'H', enabled_by='cout2_enable'),
    'Vf_din': FieldSpec('未导入曲线时压降', 'Vf,in', 'V', enabled_by='d_in_enable'),
    'Rd_din': FieldSpec('动态电阻', 'Rd,in', 'Ω', enabled_by='d_in_enable'),
    'Vf_dout': FieldSpec('未导入曲线时压降', 'Vf,out', 'V', enabled_by='d_out_enable'),
    'Rd_dout': FieldSpec('动态电阻', 'Rd,out', 'Ω', enabled_by='d_out_enable'),
    'Vgs': FieldSpec('栅极驱动电压', 'Vgs,drive', 'V', required=True),
    'Rg_drive': FieldSpec('驱动器内部电阻', 'Rg,drive', 'Ω', required=True),
    'Rs_on': FieldSpec('外部开通电阻', 'Rg,on', 'Ω', required=True),
    'Rs_off': FieldSpec('外部关断电阻', 'Rg,off', 'Ω', required=True),
    'forward_dead_time': FieldSpec('驱动死区时间', 'tdead', 's', topologies=FORWARD_TOPOLOGIES),
    # Rs also contributes a loss in voltage mode; never hide it with PCM fields.
    'Rs': FieldSpec('采样电阻', 'Rsense', 'Ω'),
    'A_sense': FieldSpec('采样放大增益', 'Asense', '倍', required=True),
    # Vm participates in voltage mode and in the DCM current-mode plant.
    'Vm': FieldSpec('调制斜坡幅值', 'Vm', 'V', required=True),
    'ma_slope': FieldSpec('输入电流等效斜坡', 'ma', 'A/s'),
    'Bmax': FieldSpec('设计最大磁密', 'Bmax', 'T', required=True),
    'Bsat': FieldSpec('饱和磁密', 'Bsat', 'T'),
    'Ku': FieldSpec('窗口填充系数', 'Ku', ''),
    'mu_r': FieldSpec('磁材相对磁导率（0=材料预设）', 'μr', '', topologies=ISOLATED_TOPOLOGIES),
    'le_core': FieldSpec('旧版磁路长度（已停用，按 Ve/Ae 派生）', 'le', 'm', topologies=ISOLATED_TOPOLOGIES),
    'Np': FieldSpec('原边匝数', 'Np', '匝', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'Ns': FieldSpec('副边匝数', 'Ns', '匝', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'd_wire_p': FieldSpec('原边单股线径', 'dp', 'm', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'd_wire_s': FieldSpec('副边单股线径', 'ds', 'm', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'n_strand_p': FieldSpec('原边单根线股数', 'np', '股', topologies=ISOLATED_TOPOLOGIES),
    'n_strand_s': FieldSpec('副边单根线股数', 'ns', '股', topologies=ISOLATED_TOPOLOGIES),
    'parallel_wires_p': FieldSpec('原边线圈并绕数', 'bp', '根', topologies=ISOLATED_TOPOLOGIES),
    'parallel_wires_s': FieldSpec('副边线圈并绕数', 'bs', '根', topologies=ISOLATED_TOPOLOGIES),
    'MLT': FieldSpec('旧版平均匝长', 'MLT', 'm'),
    'Rth_transformer': FieldSpec('变压器至环境热阻', 'Ri-a', 'K/W', required=True,
                                 topologies=ISOLATED_TOPOLOGIES),
    'h_conv': FieldSpec('电感对流换热系数', 'h', 'W/(m²·K)',
                        topologies=('BUCK', 'BOOST', 'BUCK-BOOST', 'ACF-FORWARD')),
    'temp_rise_limit': FieldSpec('温升评审上限', 'ΔTmax', 'K'),
    'rho': FieldSpec('导线电阻率', 'ρ', 'Ω·m'),
    'k_core': FieldSpec('Steinmetz 系数', 'k', 'mW/cm³·kHz⁻α·T⁻β'),
    'a_core': FieldSpec('频率指数', 'α', ''),
    'b_core': FieldSpec('磁密指数', 'β', ''),
    'KP': FieldSpec('补偿器增益', 'KP', '', required=True),
    'fz1': FieldSpec('零点 1', 'fz1', 'Hz'),
    'fz2': FieldSpec('零点 2', 'fz2', 'Hz'),
    'fp1': FieldSpec('极点 1', 'fp1', 'Hz'),
    'fp2': FieldSpec('极点 2', 'fp2', 'Hz'),
}


def applicable(key: str, topology: str, control_mode: str) -> bool:
    """Whether a field belongs to the selected model, independent of folding.

    Control-specific fields retain their stored values when hidden.
    """
    field = META[key]
    if field.topologies and topology not in field.topologies:
        return False
    if topology == 'LLC':
        if key in ('llc_hhc_sense', 'llc_hhc_ramp'):
            return control_mode == 'Hybrid Hysteretic'
        if key in ('L', 'Vf', 'Rd_diode', 'Qrr', 'Rs', 'A_sense', 'Vm', 'ma_slope',
                   'KP', 'fz1', 'fz2', 'fp1', 'fp2', 'eta_guess',
                   'Vth', 'gfs', 'mos_curve_vds', 'Vgp_on', 'Vgp_off', 'Qg_th', 'Qgs', 'Qgd',
                   'Rg', 'k_sw', 'Rg_drive', 'Rs_on', 'Rs_off'):
            return False
    cot = topology == 'BUCK' and control_mode == 'Constant On-Time'
    if key in ('cot_ton_s', 'cot_min_off_s', 'cot_kp_hz', 'cot_ki_hz_per_s') or (
            topology == 'BUCK' and key in ('Rds_aux', 'Qg_aux', 'Coss_aux')):
        return cot
    if cot and key in ('Vf_diode','Rd_diode','Qrr','Vm','KP','fz1','fz2','fp1','fp2'):
        return False
    if key in ('A_sense', 'ma_slope'):
        return control_mode in ('Peak Current Mode', 'PCM')
    return True


def visible(key: str, topology: str, control_mode: str, advanced: bool,
            flags: Mapping[str, bool]) -> bool:
    """Model/option visibility, before applying fold and search UI state.

    ``advanced`` is accepted for API compatibility but no longer hides fields.
    """
    if key in ('Rd_diode','Rd_din','Rd_dout','le_core','MLT'):return False
    from inductor_selection import TOPOLOGIES, DESIGN_FIELDS, FIELDS
    bought = topology in TOPOLOGIES and not flags.get('inductor_design_enabled', True)
    if (bought and key in DESIGN_FIELDS) or (not bought and key in FIELDS):
        return False
    field = META[key]
    return (applicable(key, topology, control_mode)
            and (not field.enabled_by or bool(flags.get(field.enabled_by, False))))
