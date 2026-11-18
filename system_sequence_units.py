"""Adapt verified converter decks into units of one switching simulation.

The canvas currently describes positive supply connections with a common return.
The global SPICE node 0 and the existing secondary-reference source therefore
remain deliberate.  This module does not infer isolated return domains, load a
user SPICE file, write files, or execute LTspice.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re


SUPPORTED_TOPOLOGIES = ('BUCK', 'BOOST', 'FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
_PARTS = ('power_stage.inc', 'coupling.inc', 'support.inc', 'parasitics.inc')
_FIXTURES = {'VIN_SOURCE', 'VEN', 'VCC_SOURCE'}
_IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,47}\Z')
_SYMBOL = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _text(files, name):
    try:
        return files[name].decode('ascii')
    except (KeyError, UnicodeDecodeError, AttributeError) as exc:
        raise ValueError(f'联合启动单元缺少有效的内置电路文件：{name}') from exc


def _rows(text):
    """Current generated decks use single-line cards; fail on new syntax."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('*'):
            continue
        if line.startswith('+'):
            raise ValueError('联合启动单元尚未支持多行 SPICE 卡片')
        yield line


def _included_files(files):
    allowed = set(_PARTS) | {'design_params.inc', 'analysis.inc'}
    included = []
    deck = _text(files, 'Flyback.cir')
    for line in _rows(deck):
        if not line.startswith('.'):
            continue  # SPICE deck title
        if line.lower() == '.end':
            continue
        match = re.fullmatch(r'\.include\s+([A-Za-z0-9_]+\.(?:inc|lib))', line, re.I)
        if not match:
            raise ValueError('联合启动仅接受内置相对 include，不支持外部路径或其他顶层指令')
        name = match[1]
        if name not in files or (name not in allowed and not name.endswith('.lib')):
            raise ValueError('联合启动不支持的内置 include：' + name)
        included.append(name)
    if len(included) != len(set(included)):
        raise ValueError('内置 SPICE 工程存在重复 include')
    required = {'design_params.inc', 'power_stage.inc', 'coupling.inc', 'support.inc', 'analysis.inc'}
    if not required.issubset(included):
        raise ValueError('内置 SPICE 工程缺少必要的电路 include')
    return included


def _library_symbols(libraries, namespace):
    """Collect across all libraries so cross-library calls get the same prefix."""
    symbols = {}
    for text in libraries.values():
        depth = 0
        for line in _rows(text):
            if line.lower().startswith('.subckt '):
                depth += 1
                name = line.split()[1]
            elif line.lower().startswith('.func '):
                name = re.split(r'[\s(]', line[6:].strip(), 1)[0]
            elif line.lower().startswith('.ends'):
                depth -= 1
                if depth < 0:
                    raise ValueError('内置控制器库的子电路边界无效')
                continue
            elif line.startswith('.'):
                if not (depth and line.lower().startswith(('.model ', '.param '))):
                    raise ValueError('内置控制器库存在不支持的全局指令：' + line.split()[0])
                continue
            else:
                continue
            if not _IDENTIFIER.fullmatch(name) or name.casefold() in symbols:
                raise ValueError('内置控制器库符号无效或重名：' + name)
            symbols[name.casefold()] = namespace + '_' + name
        if depth:
            raise ValueError('内置控制器库缺少 .ends')
    return symbols


def _rename_symbols(text, symbols):
    # Full identifier tokens prevent prefix collisions (e.g. CORE and CORE2).
    # This also covers .ends, .func calls and cross-library X calls.
    return _SYMBOL.sub(lambda match: symbols.get(match[0].casefold(), match[0]), text)


def _check_calls(text, symbols):
    declared = {value.casefold() for value in symbols.values()}
    for line in _rows(text):
        if line[0].upper() != 'X':
            continue
        tokens = line.split()
        first_parameter = next((i for i, token in enumerate(tokens) if '=' in token), len(tokens))
        model_index = first_parameter - 1
        if tokens[model_index].lower() == 'params:':
            model_index -= 1
        if model_index < 2 or tokens[model_index].casefold() not in declared:
            raise ValueError('内置电路含未解析的子电路调用：' + tokens[0])


def _controller_probes(topology, meta):
    if topology == 'QR-FLYBACK':
        return dict(run='xu_ctrl:active', filtered_cs='xu_ctrl:filtered',
                    uvlo='xu_ctrl:uv', abnormal_trip='xu_ctrl:trip')
    stem = 'xu_ctrl:xmain' if topology == 'ACF-FORWARD' else 'xu_ctrl'
    result = dict(run=stem + ':active', filtered_cs=stem + ':cs_filtered',
                  cycle_limit=stem + ':ilim')
    full = topology not in ('BUCK', 'BOOST') or bool(meta['resolved_controller']['SCMODE'])
    if full:
        result.update(ocp=stem + ':xsuper:ocp', scp=stem + ':xsuper:scp',
                      olp_state=stem + ':olpt')
    return result


def _thresholds(topology, meta):
    values = meta['resolved_controller']
    qr = topology == 'QR-FLYBACK'
    result = dict(en_on_v=.5, gate_on_v=values['VG'] / 2,
                  gate_drive_v=values['VG'], input_uvlo=None,
                  vcc_uvlo_on_v=values['UVON'] if qr else values['UVLO'],
                  vcc_uvlo_off_v=values['UVOFF'] if qr else values['UVLO'],
                  vcc_uvlo_hysteresis=qr,
                  nominal_vcc_v=values['QR_VCC'] if qr else values['VG'],
                  cycle_cs_ceiling_v=values['CS_LIM'],
                  sense_resistor_ohm=values.get('RSENSE'),
                  current_sense_gain=values['A_CS'],
                  soft_start_s=values['TSS'], enable_delay_s=0. if qr else values['TEN'],
                  cycle_blank_s=values['TLEB'] if qr else values['TBLANK'],
                  minimum_on_s=values['TONMIN'])
    if qr:
        result.update(abnormal_cs_v=values['OCP'], fault_reset='vcc-below-uvlo-off',
                      cycle_limit_definition='filtered-CS >= COMP/A_CS after blanking/minimum-on',
                      fault_model='abnormal-CS-latch', olp_enabled=False)
    else:
        short_mode = int(values['SCMODE'])
        result.update(abnormal_cs_v=values['SCP'], short_mode=short_mode,
                      fault_reset='disable-or-vcc-uvlo' if short_mode == 2 else
                      'disable-or-vcc-uvlo-or-hiccup-timer' if short_mode == 1 else 'no-latched-fault',
                      cycle_limit_definition='filtered-CS limited by ILIM; soft-start mode may lower ILIM',
                      fault_model='supervisory' if topology not in ('BUCK', 'BOOST') or short_mode else
                      'cycle-limit-only-fault-output-zero',
                      olp_enabled=bool(values['OLPEN']) and bool(short_mode),
                      olp_after_soft_start=True, hiccup_off_s=values['TOFF'],
                      soft_start_mode=int(values['SSMODE']))
    return result


def compile_unit(spec, namespace, bundle=None):
    """Return an owned switching subcircuit and its namespaced dependencies.

    ``spec`` accepts the same SI/config representation as ``load_spec``. ``bundle``
    is an optional existing endpoints runtime bundle for the same frozen hardware.
    Relative probe names must be prefixed by the outer X instance, e.g.
    ``V(xpsu01:vin_bus)``. Current probes are independent voltage monitor nodes
    with 1 V/A conversion, e.g. ``V(xpsu01:SEQ_I_LP)``. The caller owns all loads
    and EN/VCC sources. No retained BLOAD may double-count canvas consumers.
    """
    if not isinstance(namespace, str) or not _IDENTIFIER.fullmatch(namespace):
        raise ValueError('SPICE 单元命名空间须以英文字母开头，仅含字母、数字和下划线，最长48字')
    if not isinstance(spec, dict):
        raise ValueError('SPICE 单元规格须为对象')
    from config_io import decode_config
    decoded = decode_config(spec)
    topology = decoded.get('topology', 'FLYBACK')
    if isinstance(topology, str):
        topology = topology.strip().upper()
    if topology not in SUPPORTED_TOPOLOGIES:
        raise ValueError('联合开关仿真尚不支持此拓扑：' + str(topology))
    if decoded.get('feedback_mode', 'SSR') != 'SSR':
        raise ValueError('联合开关仿真尚不支持 PSR，仅支持 SSR 反馈')
    from design_engine.specification import load_spec
    from design_engine.service import calculate_parameters
    from spice_export import project_files
    p = load_spec(spec)
    from cot_settings import active as is_cot
    if bundle is None:
        bundle = calculate_parameters(p, analysis='endpoints', include_loop=False,
                                      include_cross_regulation=False).runtime_bundle()
    cases = bundle.get('cases', [])
    if not cases or any(case.get('error') or not case.get('result') for case in cases):
        raise ValueError('联合开关仿真单元的端点计算未完成')
    if any(case.get('p', {}).get('topology') != topology for case in cases):
        raise ValueError('联合开关仿真单元的计算快照拓扑不匹配')
    if is_cot(p):
        from cot_advanced_spice import compile_sequence_unit
        return compile_sequence_unit(p, namespace, bundle)
    files = project_files(p, bundle=bundle)
    included = _included_files(files)
    meta = json.loads(files['manifest.json'])
    library_text = {name: _text(files, name) for name in included if name.endswith('.lib')}
    if not library_text:
        raise ValueError('联合开关仿真单元缺少控制器库')
    symbols = _library_symbols(library_text, namespace)
    libraries = {namespace + '_' + name: _rename_symbols(text, symbols).encode('ascii')
                 for name, text in library_text.items()}
    for text in libraries.values():
        _check_calls(text.decode('ascii'), symbols)

    parameters = []
    for line in _rows(_text(files, 'design_params.inc')):
        if line.lower().startswith('.step '):
            continue
        if not line.lower().startswith('.param '):
            raise ValueError('联合开关仿真参数文件存在非参数指令')
        parameters.append(line)
    sense_card = next((line for line in parameters if line.startswith('.param RSENSE=')), None)
    if sense_card is None:
        raise ValueError('联合开关仿真单元缺少实际采样电阻参数')
    meta['resolved_controller']['RSENSE'] = float(sense_card.split('=', 1)[1])

    cards, removed = [], []
    for name in _PARTS:
        if name not in included:
            continue
        for line in _rows(_text(files, name)):
            ref = line.split()[0].upper()
            if ref in _FIXTURES or re.fullmatch(r'BLOAD\d+', ref):
                removed.append(ref)
                continue
            if line.startswith('.') and not line.lower().startswith('.model '):
                raise ValueError('联合开关仿真功率级存在不支持的指令：' + ref)
            cards.append(line)
    if not _FIXTURES.issubset(removed):
        raise ValueError('内置电路的输入/EN/VCC夹具与联合仿真契约不一致')
    # ACF has an overlap monitor in analysis.inc. Preserve actual component
    # cards while discarding every standalone-unit analysis command.
    for line in _rows(_text(files, 'analysis.inc')):
        if line.startswith('.'):
            if not line.lower().startswith(('.options ', '.tran ', '.save ', '.meas ')):
                raise ValueError('联合开关仿真分析文件存在不支持的指令')
        else:
            cards.append(line)
    cards = [_rename_symbols(line, symbols) for line in cards]
    _check_calls('\n'.join(cards), symbols)
    from isolated_outputs import output_specs
    snapshot = cases[0]['p']
    rails = output_specs(snapshot) or [snapshot]
    count = len(rails)
    if count != len(meta['hardware']['windings']):
        raise ValueError('联合开关仿真输出路数与冻结电路不匹配')
    expected_loads = {f'BLOAD{i}' for i in range(1, count + 1)}
    if expected_loads != {ref for ref in removed if ref.startswith('BLOAD')}:
        raise ValueError('内置电路的默认负载与联合仿真契约不一致')
    pins = ['input', 'en', 'vcc'] + [f'out{i}' for i in range(1, count + 1)]
    name = namespace + '_UNIT'
    refs = [line.split()[0] for line in cards if not line.startswith('.')]
    # Only the principal power inductors and sense branches are needed here.
    # Recording every resistor/capacitor current would multiply RAW size and
    # report rows without improving startup/OCP evidence.
    current_branches = {ref: ref for ref in refs if re.fullmatch(r'(?:LP|L1|LS\d+|LO\d+)',ref,re.I)}
    current_branches.update(primary='L1' if topology in ('BUCK', 'BOOST') else 'LP', sense='RS1')
    if topology in ('BUCK', 'BOOST'):
        current_branches['diode1'] = 'V_D1'
    currents = {key: 'SEQ_I_' + ref for key, ref in current_branches.items()}
    # Read branch currents from inside the unit, avoiding simulator-dependent
    # hierarchical I(...) spelling in a top-level .save. Each isolated monitor
    # node is exactly 1 V/A and never connects back into the physical stage.
    monitor_cards = [f'BSEQ_I_{ref} SEQ_I_{ref} 0 V=I({ref})'
                     for ref in dict.fromkeys(current_branches.values())]
    subckt = '\n'.join(['* Common-return switching unit; all loads and fixture sources are external.',
                        '.subckt ' + name + ' ' + ' '.join(pins)] + parameters + cards +
                       ['* Independent branch-current voltage monitors: 1 V/A.'] + monitor_cards +
                       ['.ends ' + name, ''])
    probes = dict(input='input', inputbus='vin_bus', en='en', vcc='vcc', gate='gate',
                  sense='sense', ss='ss', fault='fault', comp='comp', ramp='ramp',
                  sgnd='sgnd', drain='drain', duty='duty_mon', currents=currents,
                  controller=_controller_probes(topology, meta))
    for i in range(1, count + 1):
        probes[f'cap{i}'] = f'cap{i}'
        probes[f'out{i}'] = f'out{i}'
    if topology == 'QR-FLYBACK':
        probes['zcd'] = 'zcd'
    if topology == 'ACF-FORWARD':
        probes.update(sync='sync', auxgate='auxgate', overlap='overlap')
    outputs = [dict(id=i, name=rail.get('name') or f'OUT{i}', V_out=float(rail['V_out']),
                    P_out=float(rail['P_out']), cap_node=f'cap{i}', out_node=f'out{i}',
                    return_node='sgnd') for i, rail in enumerate(rails, 1)]
    limitations = [
        '画布仅建模正供电线，所有电源共用 SPICE 0 返回；未验证独立隔离返回域。',
        '外部 VCC 是声明的理想控制供电；未模拟启动电阻、辅助绕组供电与其掉电过程。',
        '原单元额定电阻负载已全部移除，画布层必须显式生成实际负载。',
        '输入 UVLO 与 EN 时序由画布层提供；控制器 UVLO 参数仅针对 VCC。',
    ]
    if topology == 'BUCK' and meta.get('niso', {}).get('id') == 1:
        limitations.append('TPS40200 电压模式斜坡按冻结名义 VIN 产生；动态输入跌落未实时改变前馈斜坡。')
    if topology == 'BOOST':
        limitations.append('关闭 EN 不切断 Boost 的输入电感和输出整流通路。')
    if topology == 'QR-FLYBACK':
        limitations.append('QR 异常 CS 锁存仅由 VCC 欠压复位；单独关闭 EN 不清除锁存。')
    manifest = copy.deepcopy(meta)
    manifest['sequence_unit'] = dict(
        schema='power.sequence-unit/1', namespace=namespace, subckt_name=name, pins=pins,
        common_return='0', output_count=count, removed_cards=removed,
        libraries={key: namespace + '_' + key for key in library_text},
        symbols=symbols, thresholds=_thresholds(topology, meta), limitations=limitations,
        current_probes=dict(representation='independent-voltage-monitor', scale_A_per_V=1.,
                            branches=current_branches, nodes=currents),
        source_hashes={key: hashlib.sha256(files[key]).hexdigest()
                       for key in included + ['Flyback.cir']},
        component_refs=refs, model_scope='switching-power-stage-with-generic-behavioral-controller')
    return dict(subckt_text=subckt, libraries=libraries, manifest=manifest,
                probes=probes, output_count=count, outputs=outputs)
