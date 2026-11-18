"""Generate a public synthetic power tree; never access the user's canvas.

Uses the existing shared calculator/compensator and reference component scalars.
--compile-check only prepares the switching deck in memory; it does not launch
LTspice or establish startup, protection, OR-transition or hardware compliance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

from design_engine.service import calculate_parameters
from design_engine.specification import load_spec
from loop_tuning import kfactor_tune
from plants import build_loop_models
from power_network import normalize as normalize_project
from system_sequence_config import defaults as sequence_defaults

REFERENCE_BUCK = ROOT / 'examples' / '24W_BUCK_PCM_LTC3864.json'
REFERENCE_LDO = ROOT / 'examples' / 'SYSTEM_LDO.json'
DESTINATION = ROOT / 'examples' / 'SYSTEM_STARTUP_SHUTDOWN.json'
LDO_STARTUP_REFERENCE_S = .00055
LDO_SHORT_REFERENCE_A = .355
SOURCE_SURGE_NOTE = '主/备输入保留初版2A/1A比较门限，有意展示启动浪涌整改需求；不模拟外部源限流或据此判供流能力通过。'
SOURCE_HOLDUP_NOTE = '外部主源22ms开始下电与主Buck的24ms显式EN关断独立；输入电容在源断开后仍可保持供电。24ms关EN用于观察备用接管，实际OR换流时刻仍由电容、二极管和负载共同决定。'
PG_SEQUENCE_NOTE = '后Buck等待OR达到10.5V并保持1ms，PG迟滞1V；LDO等待5V端口达到4.5V并保持0.5ms，PG迟滞0.3V。均为本例外部时序设定。'
GENERATOR_VALIDATION_NOTE = '本生成脚本只执行共享内核计算和电路导出；实际LTspice状态以独立运行凭据为准，未做实物验证。'


def _json(path):
    return json.loads(path.read_text('utf-8-sig'))


def ldo_sequence_metadata():
    """Typical datasheet references are explicit approximations, not guarantees."""
    return dict(
        inherited_reference='examples/SYSTEM_LDO.json',
        reference_sha256=hashlib.sha256(REFERENCE_LDO.read_bytes()).hexdigest(),
        scope='TLV75533参考标量及典型启动/短路电流的行为近似；非TI动态模型。',
        validation_status=GENERATOR_VALIDATION_NOTE,
        startup_current_reference=dict(document='TI TLV755P SBVS320D',
            sections=['5.5 Electrical Characteristics', '6.3.3 Current Limit'],
            url='https://www.ti.com/lit/ds/symlink/tlv755p.pdf',
            startup_typical_s=LDO_STARTUP_REFERENCE_S,
            short_circuit_typical_A=LDO_SHORT_REFERENCE_A,
            current_limit_table_A=[.560, .720, .865],
            example_reference_ramp_s=LDO_STARTUP_REFERENCE_S,
            example_fixed_limit_A=LDO_SHORT_REFERENCE_A,
            interpretation='550us为典型启动参考；355mA为典型短路电流。表列ICL与ISC不是同一保证指标，本例不复刻完整折返。'),
        assumptions=[
            '等效输出电阻0.1Ω为工程假设；额定0.5A不是保护点。',
            '本例将550us典型启动以线性参考缓升代用，将355mA典型短路电流作为固定限流；不是全温保证值或完整输出电压相关折返模型。',
            '静态Iq在0至1.45V间线性缩放仅用于低压电流合规，不是芯片UVLO或实测Iq曲线。',
            '输入UVLO4.2/3.7V及PG等待是外部示例时序，不是TLV75533本体UVLO。',
            '外部PG和负载延时采用电容计时/复位开关，复位时间常数10ns为行为近似，未复刻芯片内部PG逻辑。',
            PG_SEQUENCE_NOTE, SOURCE_SURGE_NOTE, SOURCE_HOLDUP_NOTE])


def _endpoints(p, *, loop):
    bundle = calculate_parameters(p, analysis='endpoints', include_loop=loop,
                                  include_cross_regulation=False).runtime_bundle()
    for case in bundle['cases']:
        if case.get('error') or case.get('loop_error'):
            raise ValueError(f'{case["id"]}: {case.get("error") or case.get("loop_error")}')
    return bundle


def _retuned_buck(reference, *, vmin, vmax, vout, power, role):
    """Retain the actual L/C/R/device scalars and retune only compensation."""
    p = load_spec(reference)
    p.update(V_in=vmin, V_in_min=vmin, V_in_max=vmax, input_voltage_case='min',
             V_out=vout, P_out=power, P_out_min=0., outputs=[],
             fc_target=1000., pm_target=60.)
    p['spice_config'].update(soft_start_ms=4., step_ms=12., stop_ms=18.,
                             short_test=0., fra_enabled=0., cross_enabled=0.)
    initial = _endpoints(p, loop=False)
    first = initial['cases'][0]
    plant = build_loop_models(first['p'], first['result']['op'])[0][0]
    tuned = kfactor_tune(plant, p['fc_target'], p['pm_target'], p['controller_type'])
    for key in ('KP', 'fz1', 'fz2', 'fp1', 'fp2'):
        if tuned.get(key) is not None:
            p[key] = float(tuned[key])
    final = _endpoints(p, loop=True)
    calculated = []
    for case in final['cases']:
        result = case['result']
        loop = result.get('loop') or {}
        calculated.append(dict(case=case['id'], input_V=float(case['voltage']),
            output_V=float(result['op']['V_out']), switch_peak_A=float(result['op']['I_sw_pk']),
            calculated_fc_Hz=loop.get('fc'), calculated_PM_deg=loop.get('pm'),
            calculated_closed_loop_stable=loop.get('closed_loop_stable')))
    for key, value in reference.items():
        if key.startswith('__'):
            p[key] = copy.deepcopy(value)
    p['__sequence_example'] = dict(
        role=role, inherited_reference='examples/24W_BUCK_PCM_LTC3864.json',
        reference_sha256=hashlib.sha256(REFERENCE_BUCK.read_bytes()).hexdigest(),
        component_scope='继承真实器件参考标量；没有为本电源树重新选型或通过硬件验证。',
        controller_scope='LTC3864功能参考的原创通用开关行为模型，非原厂芯片模型。',
        compensation_method='shared plants.build_loop_models + loop_tuning.kfactor_tune',
        target_fc_Hz=1000., target_PM_deg=60., calculations=calculated,
        validation_status=GENERATOR_VALIDATION_NOTE,
        assumptions=['输入UVLO、PG时序、4ms软启动、互连阻抗和附加负载电容均为本例工程设定。',
                     '保留参考L/C/ESR/DCR/Rs/MOS/二极管标量；不是新工况的原厂模型认证。',
                     PG_SEQUENCE_NOTE, SOURCE_SURGE_NOTE, SOURCE_HOLDUP_NOTE])
    return p, calculated


def _connection(identity, kind, source, target, *, mode='direct', vf=0.):
    return dict(id=identity, source=dict(kind=kind, id=source, output=1),
                target=target, mode=mode, vf=vf, enabled=True)


def build_project():
    """Return a deterministic standalone example and calculator-only receipt."""
    reference = _json(REFERENCE_BUCK)
    main, main_calculations = _retuned_buck(reference, vmin=24., vmax=24., vout=12., power=24.,
                                           role='主24V输入到12V，原额定24W硬件')
    # The inherited 47 uH / 50 kHz stage is DCM at a 3.0 W rating. The shared
    # loop implementation supports CCM only; 3.3 W is the explicit approximate
    # 3 W capacity used for compensation, never an extra simulated load.
    logic, logic_calculations = _retuned_buck(reference, vmin=11.3, vmax=11.7, vout=5., power=3.3,
                                             role='OR母线到5V/3.3W，继承硬件后重新整定补偿')
    logic['__sequence_example']['assumptions'].append(
        '额定3W在继承47µH/50kHz硬件下为DCM，现有共享环路不支持；显式采用约3W的3.3W容量整定。实际外接负载仍为2W加LDO，可能DCM，未宣称其时序环路已验证。')
    from ldo import normalize as normalize_ldo
    ldo_reference = _json(REFERENCE_LDO)['units'][0]['spec']
    ldo = copy.deepcopy(ldo_reference)
    ldo.update(V_in=4.75, V_in_min=4.75, V_in_max=5.25, V_out=3.3,
               I_out_min=0., I_out_max=.05)
    ldo = normalize_ldo(ldo)
    ldo['__sequence_example'] = ldo_sequence_metadata()
    project = dict(schema_version='power.system-network/2', title='独立示例：双Buck与LDO联合启停及二极管OR',
        revision='A',
        sources=[dict(id='BUS-MAIN', name='24V主输入', min=24., max=24., capacity=48., enabled=True),
                 dict(id='BUS-BACKUP', name='12V备用输入', min=12., max=12., capacity=12., enabled=True)],
        units=[dict(id='PSU-12V', name='LTC3864参考主Buck12V/24W', spec=main, enabled=True),
               dict(id='PSU-5V', name='LTC3864参考后级Buck5V/3.3W', spec=logic, enabled=True),
               dict(id='LDO-3V3', name='TLV75533行为LDO3.3V/50mA', spec=ldo, enabled=True)],
        junctions=[dict(id='OR-BUS', name='二极管OR母线11.3至11.7V', capacity=24., enabled=True)],
        loads=[dict(id='LOAD-OR', name='OR母线3W恒功率负载', power=3., min=9.5, max=12.2, enabled=True),
               dict(id='LOAD-5V', name='5V端口2W恒阻负载', power=2., min=4.5, max=5.5, enabled=True),
               dict(id='LOAD-3V3', name='3.3V端口50mA恒流负载', power=.165, min=3., max=3.6, enabled=True)],
        connections=[
            _connection('LINK-001', 'bus', 'BUS-MAIN', 'PSU-12V'),
            _connection('LINK-002', 'unit', 'PSU-12V', 'OR-BUS', mode='diode', vf=.3),
            _connection('LINK-003', 'bus', 'BUS-BACKUP', 'OR-BUS', mode='diode', vf=.6),
            _connection('LINK-004', 'junction', 'OR-BUS', 'PSU-5V'),
            _connection('LINK-005', 'junction', 'OR-BUS', 'LOAD-OR'),
            _connection('LINK-006', 'unit', 'PSU-5V', 'LDO-3V3'),
            _connection('LINK-007', 'unit', 'PSU-5V', 'LOAD-5V'),
            _connection('LINK-008', 'unit', 'LDO-3V3', 'LOAD-3V3')],
        activeUnit='PSU-12V', layout=dict(nodes={
            'bus:BUS-MAIN': dict(x=20., y=40.), 'bus:BUS-BACKUP': dict(x=20., y=340.),
            'unit:PSU-12V': dict(x=420., y=40.), 'junction:OR-BUS': dict(x=820., y=190.),
            'unit:PSU-5V': dict(x=1220., y=40.), 'unit:LDO-3V3': dict(x=1620., y=40.),
            'load:LOAD-OR': dict(x=1220., y=340.), 'load:LOAD-5V': dict(x=1620., y=340.),
            'load:LOAD-3V3': dict(x=2020., y=40.)}))
    project = normalize_project(project)
    cfg = sequence_defaults(project)
    cfg['settings'].update(stop_s=.04, timeout_s=600., threads=2, vin_case='min')
    cfg['sources']['BUS-MAIN'].update(on_s=0., rise_s=.002, off_s=.022, fall_s=.001,
                                      resistance_ohm=.05, inductance_H=0., current_limit_A=2., sink_current=False)
    cfg['sources']['BUS-BACKUP'].update(on_s=0., rise_s=.002, off_s=.032, fall_s=.001,
                                        resistance_ohm=.05, inductance_H=0., current_limit_A=1., sink_current=False)
    for row in cfg['units'].values():
        row.update(enable_s=0., disable_s=.035)
    cfg['units']['PSU-12V'].update(vin_on_V=18., vin_off_V=16., soft_start_s=.004, disable_s=.024)
    cfg['units']['PSU-5V'].update(vin_on_V=10., vin_off_V=9., soft_start_s=.004,
                                 wait_for_port='OR-BUS', pg_threshold_V=10.5, pg_delay_s=.001, pg_hysteresis_V=1.)
    cfg['units']['LDO-3V3'].update(vin_on_V=4.2, vin_off_V=3.7, wait_for_port='PSU-5V/OUT1',
                                  pg_threshold_V=4.5, pg_delay_s=.0005, pg_hysteresis_V=.3,
                                  soft_start_s=LDO_STARTUP_REFERENCE_S,
                                  ldo_output_current_limit_A=LDO_SHORT_REFERENCE_A,
                                  ldo_output_resistance_ohm=.1)
    cfg['loads']['LOAD-OR'].update(mode='P', power_W=3., nominal_voltage_V=11.5,
        on_V=10.6, off_V=9.5, delay_s=.0005, ramp_s=.001, input_capacitance_F=47e-6,
        input_esr_ohm=.1, bleeder_ohm=10000.)
    cfg['loads']['LOAD-5V'].update(mode='R', power_W=2., nominal_voltage_V=5.,
        on_V=4.2, off_V=3.6, delay_s=.001, ramp_s=.001, input_capacitance_F=10e-6,
        input_esr_ohm=.1, bleeder_ohm=10000.)
    cfg['loads']['LOAD-3V3'].update(mode='I', power_W=.165, nominal_voltage_V=3.3,
        on_V=2.8, off_V=2.6, delay_s=.001, ramp_s=.001, input_capacitance_F=4.7e-6,
        input_esr_ohm=.1, bleeder_ohm=33000.)
    for key, row in cfg['rail_loads'].items():
        if row['enabled']:
            raise AssertionError('全部输出已接下级，禁止重复放置额定测试负载：' + key)
    project['sequence_config'] = cfg
    project = normalize_project(project)
    receipt = dict(scope='shared-calculator-and-export-only; no-LTspice-or-hardware-run',
                   buck_calculations={'PSU-12V': main_calculations, 'PSU-5V': logic_calculations},
                   source_current_limits=SOURCE_SURGE_NOTE,
                   rated_fixture_loads={key: row['enabled'] for key, row in cfg['rail_loads'].items()})
    return project, receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DESTINATION)
    parser.add_argument('--compile-check', action='store_true', help='仅内存生成电路并核对接口，不执行LTspice')
    args = parser.parse_args(argv)
    project, receipt = build_project()
    if args.compile_check:
        from system_sequence_export import project_files
        files, manifest = project_files(project)
        receipt['compile_check'] = dict(files=len(files), sources=len(manifest['sources']),
            units=len(manifest['units']), connections=len(manifest['connections']),
            loads=len(manifest['loads']), max_step_s=manifest['max_step_s'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(project, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
