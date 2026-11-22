"""Shared presentation metadata for the desktop and local-web COT editor."""
from copy import deepcopy


def schema():
    from cot_settings import CONFIG_DEFAULTS, DYNAMIC_DEFAULTS, PHASE_DEFAULTS
    groups = []
    def group(name, fields):
        result = []
        for key, label, unit, factor, note, *choices in fields:
            default = DYNAMIC_DEFAULTS.get(key.split('.')[-1], 0.) if key.startswith('dynamic.') else CONFIG_DEFAULTS.get(key, 0.)
            result.append(dict(key=key, label=label, unit=unit, factor=factor, note=note,
                               default=default, choices=choices[0] if choices else None))
        groups.append(dict(name=name, fields=result))
    group('控制与均流', [
        ('model','控制结构','',1.,'旧工程保留原频率 PI；总电流反馈增加快速电流通道。',{'cadence_pi':'频率 PI','current_feedback':'总电流反馈 COT'}),
        ('controller_reference','结构参考','',1.,'原厂公开结构的行为参考；增益为本模型单位。',{'generic':'通用 1–16 相','ti_dcap_plus':'TI D-CAP+ 公开结构参考'}),
        ('current_feedback_hz_per_a','总电流反馈增益','Hz/A',1.,'电流增加时降低触发频率；与电流采样滤波共同决定动态。'),
        ('current_filter_hz','电流采样滤波带宽','kHz',1e-3,'总电流通道的一阶低通带宽。'),
        ('balance_gain_v_per_a','均流调节增益','V/A',1.,'按各相测量电流差修正导通时间；0 为关闭。'),
        ('balance_bandwidth_hz','均流调节带宽','kHz',1e-3,'均流通道的一阶动态带宽。'),
        ('balance_max_duty','均流占空比修正上限','%',100.,'限制每相脉宽修正，百分比为绝对占空比。'),
        ('phase_imbalance_limit_pct','允许相间偏流','%',1.,'各相相对平均电流的最大偏差。'),
    ])
    group('保护与驱动', [
        ('phase_limit_A','每相限流阈值','A',1.,'按该相采样电流判断；0 为停用。'),
        ('limit_delay_s','限流检测延迟','ns',1e9,'采样超过限值至保护动作的等效延迟。'),
        ('fault_mode','故障恢复方式','',1.,'持续过流后的恢复策略。',{'cycle':'逐周期限流','hiccup':'打嗝重启','latch':'锁存关断'}),
        ('fault_delay_s','持续故障判定时间','ms',1e3,'进入打嗝或锁存前的持续故障时间。'),
        ('hiccup_s','打嗝等待时间','ms',1e3,'故障关断后等待再启动的时间。'),
        ('uvlo_on_V','输入启动阈值','V',1.,'输入母线达到该值才允许启动；0 为停用。'),
        ('uvlo_off_V','输入关断阈值','V',1.,'与启动阈值共同形成欠压迟滞。'),
        ('vcc_uvlo_V','控制器供电欠压阈值','V',1.,'控制器 VCC 低于该值时关断门极；0 为停用。'),
        ('ovp_V','输出过压阈值','V',1.,'防反管前电容端的过压阈值；0 为停用。'),
        ('dead_time_s','上下管死区','ns',1e9,'上下功率管换流时共同关闭的时间。'),
        ('body_diode_V','体二极管导通拐点电压','V',1.,'通用开关模型另含 5 mΩ 斜率电阻；导通压降随电流增加。'),
        ('body_qrr_C','低侧体二极管恢复电荷','nC',1e9,'器件指定测试条件的 Qrr，用于恢复损耗估计。'),
        ('light_load','轻载运行方式','',1.,'二极管仿真在电感电流过零时关闭低侧。',{'forced':'强制同步','diode_emulation':'二极管仿真'}),
    ])
    group('供电与动态负载', [
        ('source_resistance_ohm','输入源串联电阻','mΩ',1e3,'连接器与输入供电路径的等效串联电阻。'),
        ('source_inductance_H','输入源串联电感','µH',1e6,'输入线缆与供电路径的等效串联电感。'),
        ('source_rise_s','输入电压上升时间','ms',1e3,'0 为理想阶跃；用于检查输入电容充电浪涌。'),
        ('prebias_V','输出预偏置','V',1.,'仿真启动前输出电容的初始电压。'),
        ('shutdown_s','主动关机时刻','ms',1e3,'0 为本次不安排关机；需早于仿真结束。'),
        ('load_mode','电路仿真负载类型','',1.,'电阻负载随电压变化，恒流负载按设定时序加载。',{'resistance':'电阻负载','current':'恒流负载'}),
        ('load_rise_s','仿真负载变化时间','µs',1e6,'负载阶跃的实际边沿时间。'),
        ('dynamic.step_A','电容选型负载变化量','A',1.,'选型校核的负载阶跃幅度；0 表示未声明。'),
        ('dynamic.rise_s','选型负载边沿时间','µs',1e6,'负载从原值变化到新值所用时间。'),
        ('dynamic.delay_s','控制响应延迟','µs',1e6,'控制开始有效补充电流前的估计延迟。'),
        ('dynamic.droop_V','允许输出跌落','mV',1e3,'端口电压允许的动态欠调幅值。'),
        ('dynamic.overshoot_V','允许输出过冲','mV',1e3,'端口电压允许的动态过冲幅值。'),
    ])
    from cot_acceptance import DEFAULT_LIMITS
    from loop_acceptance import MIN_PHASE_MARGIN_DEG
    group('报告验收', [
        ('acceptance.gm_min_db','最小增益裕度','dB',1.,'有效频带未覆盖相位穿越时标记未覆盖。'),
        ('acceptance.fc_error_pct','计算与仿真 fc 允许偏差','%',1.,'两者穿越频率偏差的限值。'),
        ('acceptance.pm_error_deg','计算与仿真 PM 允许偏差','°',1.,'两者相位裕度差的绝对值。'),
        ('acceptance.gain_error_db','同频增益允许偏差','dB',1.,'计算与仿真有效同频点的增益差。'),
        ('acceptance.phase_error_deg','同频相位允许偏差','°',1.,'计算与仿真有效同频点的相位差。'),
        ('acceptance.overshoot_pct','允许启动／动态过冲','%',1.,'动态电压限值填写后，以其为准。'),
        ('acceptance.undershoot_pct','允许动态跌落','%',1.,'动态电压限值填写后，以其为准。'),
        ('acceptance.settling_band_pct','恢复判定电压带','%',1.,'输出进入并保持在设定电压带内。'),
        ('acceptance.recovery_s','最大恢复时间','ms',1e3,'从负载变化起计时。'),
        ('acceptance.input_peak_A','输入峰流限值','A',1.,'0 为仅观察，不判定输入浪涌通过。'),
    ])
    groups[-1]['note'] = f'FRA 最小相位裕度验收要求严格大于 {MIN_PHASE_MARGIN_DEG:g}°。'
    for field in groups[-1]['fields']:
        field['default']=DEFAULT_LIMITS[field['key'].split('.')[-1]]
    phase_labels = {'L_scale':'电感倍率','dcr_scale':'DCR 倍率','rhigh_scale':'高侧 Rds 倍率',
                    'rlow_scale':'低侧 Rds 倍率','ton_scale':'导通定时倍率',
                    'sense_gain':'采样增益倍率','sense_offset_A':'采样偏置 / A'}
    return dict(groups=groups, defaults=deepcopy(CONFIG_DEFAULTS), dynamic_defaults=deepcopy(DYNAMIC_DEFAULTS),
                phase_defaults=deepcopy(PHASE_DEFAULTS),
                phase_fields=[dict(key=k,label=phase_labels[k]) for k in PHASE_DEFAULTS])


def get_value(data, path, default=None):
    for key in path.split('.'):
        if not isinstance(data, dict) or key not in data:
            return default
        data=data[key]
    return data


def set_value(data, path, value):
    parts=path.split('.')
    for key in parts[:-1]:
        data=data.setdefault(key,{})
    data[parts[-1]]=value
