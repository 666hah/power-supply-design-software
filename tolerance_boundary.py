"""Physical candidate selection for the quick fixed-hardware boundary study."""

from math import isfinite, sqrt

from tolerance_defaults import PSR_AUTO_DIVIDER_SCALE, TRANSFORMER_SCALE


_DIVIDER = 'tolerance_feedback_divider.'
_DIVIDER_UPPER = _DIVIDER + 'upper_ohm'
_DIVIDER_LOWER = _DIVIDER + 'lower_ohm'
_MAGNETIZING = (TRANSFORMER_SCALE, 'Lm_forward', 'llc_lm')
_FEEDBACK_LOW = {'lower_ohm': 'high', 'upper_ohm': 'low'}
_OPPOSITE = {'high': 'low', 'low': 'high'}


def _feedback_limits(fixed, variables):
    divider = fixed.get('tolerance_feedback_divider')
    targets = {_DIVIDER_UPPER, _DIVIDER_LOWER}
    if not divider or not any(row['path'] in targets and row['low'] != row['high'] for row in variables):
        return []

    def bound(choices):
        values = {row['path']: row[choices[row['path'].removeprefix(_DIVIDER)]]
                  for row in variables if row['path'] in targets}
        upper = values.get(_DIVIDER_UPPER, divider['upper_ohm'])
        lower = values.get(_DIVIDER_LOWER, divider['lower_ohm'])
        return divider['reference_V'] * (1 + upper/lower), values

    low, low_parameters = bound(_FEEDBACK_LOW)
    high, high_parameters = bound({key: _OPPOSITE[side] for key, side in _FEEDBACK_LOW.items()})
    if not all(isfinite(voltage) for voltage in (low, high)):
        return []
    output = divider['output']
    return [dict(id='feedback_divider_static', label=f'OUT{output} 反馈取样点直流设定幅值',
                 formula='Vref × (1 + R上/R下)', unit='V', output=output,
                 scope='基准电压固定时，上臂电阻越大、下臂电阻越小，设定幅值越高。'
                       '此值为防反管前的取样设定，端口包络仍由电路复算。',
                 nominal=divider['reference_V'] * (1 + divider['upper_ohm']/divider['lower_ohm']),
                 low=low, high=high, low_parameters=low_parameters, high_parameters=high_parameters)]


def _buck_capacitive_limits(fixed, variables):
    from cot_settings import active as is_cot

    if fixed['topology'] != 'BUCK' or is_cot(fixed):
        return []
    bank = fixed.get('output_capacitors') or ()
    caps = {f'output_capacitors.{i}.C': cap['C'] for i, cap in enumerate(bank)}
    ranges = {row['path']: row for row in variables if row['path'] in caps or row['path'] == 'L'}
    if not caps or not ranges:
        return []
    low_line, high_line = fixed['V_in_min'], fixed['V_in_max']
    output, frequency = fixed['V_out'], fixed['f_sw']
    if not all(isfinite(value) and value > 0 for value in (output, frequency, fixed['L'])) or output >= low_line:
        return []

    def values(side, voltage):
        parameters = {key: row[side] for key, row in ranges.items()}
        capacitance = sum(parameters.get(key, nominal) for key, nominal in caps.items())
        inductance = parameters.get('L', fixed['L'])
        delta_i = output*(1-output/voltage)/(frequency*inductance)
        return delta_i/(8*frequency*capacitance), delta_i, parameters

    low, _, low_parameters = values('high', low_line)
    high, peak_current_ripple, high_parameters = values('low', high_line)
    if fixed['P_out']/output <= peak_current_ripple/2 or not all(isfinite(value) for value in (low, high)):
        return []
    return [dict(id='buck_ideal_capacitive_ripple', label='OUT1 理想 CCM 电容充放电纹波', unit='V', output=1,
                 low=low, high=high, low_parameters=low_parameters, high_parameters=high_parameters,
                 formula='Vpp = Vo × (1 − Vo/Vin)/(8 × L × CΣ × fsw²)',
                 scope='额定负载、固定输出电压和频率。最大值取 Vinmax、Lmin 和最小总电容，最小值取反向边界。'
                       '本式计算纯电容纹波分量，ESR、ESL 和器件压降由整机复算。')]


def _split_paths(variables):
    """Identify banks or phases for the fixed-budget mismatch candidate."""
    banks, phases = {}, set()
    for row in variables:
        if row['low'] == row['high']:
            continue
        parts = row['path'].split('.')
        if len(parts) >= 3 and parts[-3] in ('input_capacitors', 'output_capacitors'):
            banks.setdefault('.'.join(parts[:-2]), set()).add(int(parts[-2]))
        elif parts[:2] == ['cot_config', 'phase_parameters']:
            phases.add(int(parts[2]))
    return banks, phases


def boundary_candidates(fixed, variables):
    """Return at most seven named hardware vectors and separate analytic results.

    End values delegated to an individual direction rule remain candidates for
    the complete circuit. Proof for an intermediate quantity lives separately.
    """
    nominal = tuple(row['nominal'] for row in variables)
    candidates = {'标称硬件': nominal}
    seen = {nominal}

    def add(label, values):
        if values not in seen:
            candidates[label] = values
            seen.add(values)

    def add_sides(label, sides):
        add(label, tuple(row[sides.get(row['path'], 'nominal')] for row in variables))

    proof = _feedback_limits(fixed, variables) + _buck_capacitive_limits(fixed, variables)
    active = [row for row in variables if row['low'] != row['high']]
    if len(active) <= 1:
        if active:
            for key, label in (('low', '单参数下限'), ('high', '单参数上限')):
                add_sides(label, {active[0]['path']: key})
        return list(candidates.items()), proof

    isolated = fixed['topology'] in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD', 'LLC')
    output_choke = fixed['topology'] not in ('FLYBACK', 'QR-FLYBACK', 'LLC')
    ripple, stress, thermal, feedback = {}, {}, {}, {}
    for row in active:
        path = row['path']
        name = path.rsplit('.', 1)[-1]
        if path.startswith(_DIVIDER):
            side = _FEEDBACK_LOW.get(name)
            if side:
                feedback[path] = side
            continue
        if name in ('C', 'llc_cr', 'llc_lr', 'psr_Ccomp', 'psr_Cpole') or (
                output_choke and name in ('L', 'L_scale')):
            ripple[path] = 'low'
        elif name in ('ESR', 'ESL', 'psr_Rcomp', 'psr_Rreg', 'llc_hhc_sense', 'llc_hhc_ramp'):
            ripple[path] = 'high'
        elif name in ('Vf_diode', 'Vf_dout', 'Rds_on', 'Rds_aux', 'Rth_transformer',
                      'inductor_dcr', 'llc_tank_r', 'llc_rect_r', 'dcr_scale',
                      'rhigh_scale', 'rlow_scale'):
            thermal[path] = 'high'
        elif name in _MAGNETIZING or (isolated and path == 'L' and not output_choke):
            stress[path], thermal[path] = 'low', 'high'
        elif name in ('K', 'C_clamp', 'qr_rcd_C_scale', 'llc_dead_time', 'Rs',
                      'phase_limit_A'):
            stress[path] = 'low'
        else:
            stress[path] = 'high'

    if feedback:
        output_bias = {path: side for path, side in ripple.items() if 'output_capacitors.' in path}
        high = {path: _OPPOSITE[side] for path, side in feedback.items()}
        drops = {path: side for path, side in thermal.items() if path.endswith('Vf_dout')}
        add_sides('反馈低设定与纹波候选', output_bias | feedback | drops)
        add_sides('反馈高设定与纹波候选',
                  output_bias | high | {path: _OPPOSITE[side] for path, side in drops.items()})

    # A smaller output blocking drop can raise the port voltage whenever
    # the sense point stays regulated.
    lower_drop = {path: 'low' for path in thermal if path.endswith('Vf_dout')}
    add_sides('低电容量与电感纹波候选', ripple | lower_drop)
    add_sides('峰值电流与开关应力候选',
              {path: side for path, side in ripple.items() if path.rsplit('.', 1)[-1] in ('L', 'L_scale')}
              | stress)
    # Cover opposing component directions while keeping the number of circuits
    # independent of how many capacitors, inductors or windings are selected.
    reverse = {path: _OPPOSITE[side] for path, side in (ripple | stress).items()}
    add_sides('温升与反向参数偏差候选', reverse | thermal)

    banks, phases = _split_paths(active)
    mismatch = {}
    for row in active:
        path = row['path']
        bank, _, name = path.rpartition('.')
        bank, _, index = bank.rpartition('.')
        if len(banks.get(bank, ())) > 1:
            first = min(banks[bank]) == int(index)
            if name in ('C', 'ESR', 'ESL'):
                mismatch[path] = 'high' if (name == 'C') == first else 'low'
        elif phases and path.startswith('cot_config.phase_parameters.'):
            phase = int(path.split('.')[2])
            key = 'high' if name == 'ton_scale' else 'low'
            mismatch[path] = key if phase == min(phases) else _OPPOSITE[key]
        elif path in ('psr_RfbH', 'psr_RfbL', PSR_AUTO_DIVIDER_SCALE):
            mismatch[path] = 'high' if path == 'psr_RfbH' else 'low'
    add_sides('电容分流与相间失配候选', mismatch)
    return list(candidates.items()), proof


def interior_conditions(fixed):
    """Full-load Buck interior candidates from a triangular CCM input current."""
    from cot_settings import active as is_cot
    from nonisolated import is_enabled
    from voltage_nodes import input_drop, output_drop

    if fixed['topology'] != 'BUCK' or is_cot(fixed):
        return []
    lo, hi = fixed['V_in_min'], fixed['V_in_max']
    if lo == hi:
        return []
    voltage, power = fixed['V_out'], fixed['P_out']
    inductance, frequency = fixed['L'], fixed['f_sw']
    loss_offset, drop_in = 0., 0.
    if is_enabled(fixed):
        spice = fixed['spice_config']
        frequency = spice.get('frequency_hz') or frequency
        current = power/voltage
        dcr = (fixed.get('inductor_dcr', 0.) if fixed.get('inductor_design_enabled') is False
               else max(0., spice.get('niso_inductor_dcr', -1.)))
        off = fixed['Vf_diode'] + current*(dcr + .001)
        loss_offset = current*(fixed['Rds_on'] + fixed['Rs'] + dcr) - off
        voltage += output_drop(fixed) + off
        drop_in = input_drop(fixed)
    current = power/fixed['V_out']
    ramp = voltage/(inductance*frequency)
    # Icin² = Io² D(1-D) + D ΔIL²/12, where ΔIL = ramp (1-D).
    # Maximize the CCM expression using the smaller root of its derivative.
    # Scale by the larger current before squaring to keep the roots well scaled.
    scale = max(current, ramp)
    if not isfinite(scale) or scale <= 0:
        return []
    i2, k = (current/scale)**2, (ramp/scale)**2/12
    b, c = 2*i2 + 4*k, i2 + k
    duty = 2*c/(b + sqrt(max(0., b*b - 12*k*c)))
    edge = 1 - 2*(current/ramp) if ramp > 0 else 0.

    duties = [(edge, 'Buck CCM／DCM 分界候选')]
    if duty > edge:
        duties.insert(0, (duty, 'Buck 输入纹波 RMS 候选'))
    conditions = []
    for value, label in duties:
        if 0 < value < 1:
            vin = voltage/value + drop_in + loss_offset
            if lo < vin < hi:
                conditions.append((vin, 'min', label, (1.,)))
    return conditions


def refine_buck_ripple_input(points):
    """Propose one interior point from three measured nearby RMS values."""
    by_voltage = {voltage: rms for voltage, rms in points
                  if voltage is not None and rms is not None and isfinite(voltage) and isfinite(rms)}
    ordered = sorted(by_voltage.items())
    if len(ordered) < 3:
        return None
    peak = max(range(len(ordered)), key=lambda index: ordered[index][1])
    start = min(max(0, peak - 1), len(ordered) - 3)
    (a, fa), (b, fb), (c, fc) = ordered[start:start + 3]
    resolution = max(.02, .001*(ordered[-1][0] - ordered[0][0]))
    if min(b-a, c-b) <= resolution:
        return None
    slope_left, slope_right = (fb-fa)/(b-a), (fc-fb)/(c-b)
    curve = (slope_right - slope_left)/(c-a)
    if curve >= 0:
        return None
    voltage = (a+b)/2 - slope_left/(2*curve)
    if a < voltage < c and all(abs(voltage - seen) > resolution for seen in by_voltage):
        return voltage
    return None
