"""Curated examples shared by the desktop menu and local web UI.

Other example files remain available for regression and historical evidence;
the isolated examples and Buck/Boost control references are advertised.
"""

from pathlib import Path
import sys

from app_resources import ROOT, resource_path


PUBLIC_QR = '90W_QR_L6565_252_442V_REFERENCE.json'
PERSONAL_QR = '90W_QR_L6565_252_442V.json'
PERSONAL_QR_LABEL = '准谐振反激 · L6565 · 252–442V / 92W · 本机原工程'

EXAMPLES = {
    '33W_3OUT_ACF_MP6005_COMPACT.json': '三路有源钳位正激 · MP6005 · 小电感',
    '40W_CCM_3OUT_FLYBACK.json': '三路 CCM 反激 · 用户配置',
    PUBLIC_QR: '准谐振反激 · L6565 · 252–442V / 92W · 合成参考',
    '24W_BUCK_VM_TPS40200.json': 'Buck 电压模式 · TPS40200 参考 · 24W',
    '24W_BUCK_PCM_LTC3864.json': 'Buck 峰值电流 · LTC3864 参考 · 24W',
    '96W_BUCK_COT_4PH.json': '四相同步 Buck · COT · 1.2V / 80A',
    '300W_LLC_HALF_HHC.json': '半桥 LLC · 混合滞环 · 360–420V / 48V / 300W',
    '300W_LLC_FULL_VCO.json': '全桥 LLC · 电压变频 · 360–420V / 48V / 300W',
    '24W_BOOST_PCM_LM5022.json': 'Boost 峰值电流 · LM5022 参考 · 24W',
    '24W_BUCK_CAP_IMPEDANCE.json': 'Buck · 并联电容阻抗与温升 · 合成数据',
}


def example_path(filename):
    if filename == PERSONAL_QR:
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent/'user_data'/'examples'/PERSONAL_QR
        return ROOT/'examples'/PERSONAL_QR
    return resource_path(f'examples/{filename}')


def available_examples():
    if not example_path(PERSONAL_QR).is_file():
        return dict(EXAMPLES)
    return {
        (PERSONAL_QR if name == PUBLIC_QR else name):
        (PERSONAL_QR_LABEL if name == PUBLIC_QR else label)
        for name, label in EXAMPLES.items()
    }


def example_device_defaults(filename, config):
    """Apply selected parts when opening the local QR from the example menu."""
    if filename == PERSONAL_QR:
        from example_qr_margin import personal_qr_with_margin

        return personal_qr_with_margin(config)
    return config


def tl431_network_key(output_voltage):
    """Choose the reference LED feed by the feedback output's nominal voltage."""
    return 'tl431nf' if abs(float(output_voltage)) > 31. else 'tl431f'


def example_feedback_defaults(config):
    """Apply the built-in SSR example policy without editing a user's saved file."""
    from config_io import decode_config
    from power_stage import DEFAULT_PARAMS

    params = decode_config(config)
    if params.get('topology') not in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD', 'LLC'):
        return config
    if params.get('feedback_mode') == 'PSR-MP6005':
        return config
    rails = params.get('outputs') or [params]
    rail = decode_config(rails[int(params.get('feedback_output', 1))-1])
    key = tl431_network_key(rail.get('V_out', params.get('V_out', DEFAULT_PARAMS['V_out'])))
    from compensation_report import network_key

    current = config.get('__comp') or {}
    try:
        if network_key(current.get('key') or current.get('topo', '')) == key:
            return config
    except ValueError:
        pass
    values = dict(R1=(40., 'k'), CTR=(1., ''), Rpullup=(10., 'k'), Copto=(100., 'p'))
    if key == 'tl431nf':
        values['R_LED'] = (1., 'k')
    state = dict(topo=key, dir='fwd', type2=False,
                 vars={name: dict(v=value, u=unit) for name, (value, unit) in values.items()})
    return dict(config, __comp=state)
