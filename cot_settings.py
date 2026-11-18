"""Shared settings contract for the synchronous Buck COT model."""
import math
from copy import deepcopy


COT_MODE = 'Constant On-Time'
MAX_PHASES = 16
GAIN_DEFAULTS = {'cot_kp_hz': 0., 'cot_ki_hz_per_s': 0.}
DEFAULTS = {'buck_phases': 1, 'cot_ton_s': 0., 'cot_min_off_s': 0., 'cot_config': {}, **GAIN_DEFAULTS}

PHASE_DEFAULTS = dict(L_scale=1., dcr_scale=1., rhigh_scale=1., rlow_scale=1.,
                      ton_scale=1., sense_gain=1., sense_offset_A=0.)
CONFIG_DEFAULTS = dict(model='cadence_pi', controller_reference='generic',
                       current_feedback_hz_per_a=0., current_filter_hz=20000.,
                       balance_gain_v_per_a=0., balance_bandwidth_hz=10000., balance_max_duty=.05,
                       phase_limit_A=0., limit_delay_s=20e-9, fault_mode='cycle',fault_delay_s=.0002,
                       hiccup_s=.002,uvlo_on_V=0.,uvlo_off_V=0.,ovp_V=0.,dead_time_s=0.,
                       light_load='forced',source_resistance_ohm=0.,source_inductance_H=0.,
                       source_rise_s=0.,
                       prebias_V=0.,shutdown_s=0.,load_mode='resistance',load_rise_s=1e-6,
                       body_diode_V=.7,body_qrr_C=0.,vcc_uvlo_V=0.,phase_imbalance_limit_pct=10.)
DYNAMIC_DEFAULTS = dict(step_A=0., rise_s=1e-6, delay_s=1e-6, droop_V=0., overshoot_V=0.)


def configuration(p):
    """Validated private SI contract. An absent config preserves the legacy model."""
    raw = p.get('cot_config',{})
    if raw is None:raw={}
    if not isinstance(raw, dict):
        raise ValueError('COT 工程配置须为字典')
    cfg = deepcopy(CONFIG_DEFAULTS | raw)
    # One canonical current-sharing limit for calculation and report. Old
    # report-only projects migrate here; an explicit shared field takes priority.
    acceptance=raw.get('acceptance') or {}
    if not isinstance(acceptance,dict):
        raise ValueError('COT 验收配置须为字典')
    legacy_limit=acceptance.get('imbalance_pct')
    if 'phase_imbalance_limit_pct' not in raw and legacy_limit is not None:
        cfg['phase_imbalance_limit_pct']=legacy_limit
    if isinstance(cfg.get('acceptance'),dict):
        cfg['acceptance']['imbalance_pct']=cfg['phase_imbalance_limit_pct']
    if cfg['model'] not in ('cadence_pi', 'current_feedback'):
        raise ValueError('COT 控制结构需为 cadence_pi 或 current_feedback')
    for key,values in dict(controller_reference=('generic','ti_dcap_plus'),fault_mode=('cycle','hiccup','latch'),
                           light_load=('forced','diode_emulation'),load_mode=('resistance','current')).items():
        if cfg[key] not in values:
            raise ValueError(f'COT {key} 选项不正确')
    for key in (k for k,v in CONFIG_DEFAULTS.items() if isinstance(v,(int,float))):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'COT {key} 须为有限非负数')
    if cfg['model'] == 'current_feedback' and (cfg['current_feedback_hz_per_a'] <= 0 or cfg['current_filter_hz'] <= 0):
        raise ValueError('总电流反馈的增益与滤波频率必须大于零')
    if cfg['balance_gain_v_per_a'] and (cfg['balance_bandwidth_hz'] <= 0 or not 0 < cfg['balance_max_duty'] < .5):
        raise ValueError('均流带宽需大于零，占空比修正上限需在 (0, 0.5) 内')
    if cfg['uvlo_off_V']>cfg['uvlo_on_V']:
        raise ValueError('UVLO 关断阈值不可高于启动阈值')
    count = int(p.get('buck_phases',1))
    rows = cfg.get('phase_parameters')
    if rows is None:
        rows = [{} for _ in range(count)]
    if not isinstance(rows,list) or len(rows) != count:
        raise ValueError(f'COT 每相参数必须恰好 {count} 条；改变相数时请同步调整列表')
    phases = []
    for i, row in enumerate(rows,1):
        if not isinstance(row,dict) or set(row)-set(PHASE_DEFAULTS):
            raise ValueError(f'第 {i} 相参数字段不正确')
        row = PHASE_DEFAULTS | row
        for key,value in row.items():
            if (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)
                    or (key != 'sense_offset_A' and value <= 0)):
                raise ValueError(f'第 {i} 相 {key} 需为有限数，比例须大于零')
        phases.append(row)
    cfg['phase_parameters'] = phases
    dyn = cfg.get('dynamic',{})
    if dyn is None:dyn={}
    if not isinstance(dyn,dict) or set(dyn)-set(DYNAMIC_DEFAULTS):
        raise ValueError('COT 动态约束字段不正确')
    cfg['dynamic'] = DYNAMIC_DEFAULTS | dyn
    for key,value in cfg['dynamic'].items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'COT 动态 {key} 须为有限非负数')
    from cot_acceptance import limits
    limits(dict(p,cot_config=cfg))
    return cfg


def active(p):
    return p.get('topology') == 'BUCK' and (
        p.get('control_mode') == COT_MODE or p.get('buck_phases', 1) > 1)


def configured_gains(p):
    kp = p.get('cot_kp_hz', GAIN_DEFAULTS['cot_kp_hz'])
    ki = p.get('cot_ki_hz_per_s', GAIN_DEFAULTS['cot_ki_hz_per_s'])
    for value in (kp, ki):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError('COT PI 增益须为有限非负数')
    if kp > 0 and ki == 0:
        raise ValueError('COT 手动 PI 的 Ki 必须大于 0。两个增益填 0 时自动选值')
    return float(kp), float(ki)


def validate(p):
    phases = p.get('buck_phases', 1)
    if (isinstance(phases, bool) or not isinstance(phases, (int, float)) or
            not math.isfinite(phases) or not 1 <= phases <= MAX_PHASES or phases != int(phases)):
        raise ValueError(f'Buck 相数需为 1–{MAX_PHASES} 的整数')
    if p.get('topology') != 'BUCK' and (phases != 1 or p.get('control_mode') == COT_MODE):
        raise ValueError('COT 控制和多相设置适用于 Buck')
    if active(p):
        configured_gains(p)
        configuration(p)
        if p.get('outputs') or (p.get('coupling_config') or {}).get('enabled'):
            raise ValueError('多相 Buck 的各相应接同一输出，不能使用隔离输出或变压器耦合设置')
        for key, label in (('cot_ton_s', 'COT 固定导通时间'), ('cot_min_off_s', 'COT 最小关断时间'),
                           ('Qg_aux', '低侧 MOS 栅电荷'), ('Coss_aux', '低侧 MOS 输出电容')):
            value = p.get(key, 0.)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{label}须为有限非负数')
    return int(phases)
