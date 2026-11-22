"""Default manufacturing distributions for active, modeled components."""

from math import atan2, cos, degrees, hypot, isfinite, pi, radians, sin


TRANSFORMER_SCALE = 'transformer_L_scale'
PSR_AUTO_DIVIDER_SCALE = 'psr_RfbL_scale'
QR_RCD_COMPONENTS = {
    'qr_rcd_R_scale': ('QR RCD 钳位电阻倍率', 'R_ohm', .01),
    'qr_rcd_C_scale': ('QR RCD 钳位电容倍率', 'C_F', .10),
}
PSR_RESISTORS = {
    'psr_RfbH': 'PSR 分压上电阻',
    'psr_RfbL': 'PSR 分压下电阻',
    'psr_Rreg': 'PSR SENSE 补偿电阻',
    'psr_Rcomp': 'PSR COMP 电阻',
}
RESISTORS = {
    'Rs': '电流采样电阻',
    'Rs_on': 'MOS 开通外接栅极电阻',
    'Rs_off': 'MOS 关断外接栅极电阻',
    **PSR_RESISTORS,
}
DIVIDER_RESISTORS = {
    'upper_ohm': 'SSR 反馈分压上电阻',
    'lower_ohm': 'SSR 反馈分压下电阻',
}
PSR_CAPACITORS = {'psr_Ccomp': 'PSR COMP 串联电容', 'psr_Cpole': 'PSR COMP 并联电容'}


def _field_inductances(spec):
    coupling = spec.get('coupling_config') or {}
    return coupling.get('self_inductances_H') if coupling.get('enabled') else None


def extra_variables(spec):
    """Expose physical passives omitted from the original corner catalog."""
    topology = spec['topology']
    rows = []

    def add(path, label, unit, nominal):
        if isinstance(nominal, (int, float)) and not isinstance(nominal, bool) and isfinite(nominal) and nominal > 0:
            rows.append(dict(path=path, label=label, unit=unit, nominal=float(nominal),
                             positive=True, upper=None, signed=False))

    if topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD') and _field_inductances(spec):
        add(TRANSFORMER_SCALE, '变压器场解自感矩阵整体倍率', '', 1.)

    paths = [] if topology == 'LLC' else ['Rs_on', 'Rs_off']
    if spec.get('feedback_mode') == 'PSR-MP6005':
        paths.extend((*PSR_RESISTORS, *PSR_CAPACITORS))
        if not spec.get('psr_RfbL'):
            add(PSR_AUTO_DIVIDER_SCALE, 'PSR 自动选定分压下电阻倍率', '', 1.)
    if (topology == 'QR-FLYBACK' and len(spec.get('outputs') or []) > 1
            and (spec.get('coupling_config') or {}).get('enabled')):
        for path, (label, _, _) in QR_RCD_COMPONENTS.items():
            add(path, label, '', 1.)
    for path in paths:
        # Zero may be a shorting link or the automatic PSR divider selection.
        label = RESISTORS.get(path) or PSR_CAPACITORS[path]
        add(path, label, 'Ω' if path in RESISTORS else 'F', spec.get(path))
    divider = spec.get('tolerance_feedback_divider') or {}
    for name, label in DIVIDER_RESISTORS.items():
        add(f'tolerance_feedback_divider.{name}', label, 'Ω', divider.get(name))
    return rows


def default_variables(spec):
    """Return absolute SI limits and σ; the requested accuracy is the ±3σ limit."""
    from tolerance_analysis import available_variables

    primary = {'FLYBACK': 'L', 'QR-FLYBACK': 'L', 'ACF-FORWARD': 'Lm_forward', 'LLC': 'llc_lm'}
    capacitors = {'C_clamp', 'llc_cr', *PSR_CAPACITORS}
    rows = []
    for item in available_variables(spec):
        path, nominal = item['path'], item['nominal']
        if nominal <= 0:
            continue
        if path.endswith('.C') or path in capacitors:
            fraction = .10
        elif path in RESISTORS or path == PSR_AUTO_DIVIDER_SCALE or path.startswith('tolerance_feedback_divider.'):
            fraction = .01
        elif path == primary.get(spec['topology']) or path == TRANSFORMER_SCALE:
            fraction = .05
        elif path in QR_RCD_COMPONENTS:
            fraction = QR_RCD_COMPONENTS[path][2]
        else:
            continue
        delta = nominal*fraction
        rows.append(dict(path=path, nominal=nominal, low=nominal-delta, high=nominal+delta,
                         sigma=delta/3, distribution='normal',
                         source=f'工程默认 ±{fraction:.0%}（±3σ 截断正态假设）'))
    return rows


def example_tolerance_defaults(config):
    """Select nominal-relative presets for built-in examples at load time."""
    if '__tolerance' in config:
        return config
    return dict(config, __tolerance={'automatic_defaults': True})


def apply_special_tolerance(spec, path, value):
    """Keep the sampled transformer/curve consistent with its nominal representation."""
    if path == PSR_AUTO_DIVIDER_SCALE:
        spec['psr_RfbL'] *= value
        return True
    if path in QR_RCD_COMPONENTS:
        _, key, _ = QR_RCD_COMPONENTS[path]
        spec['_qr_rcd_hardware'][key] *= value
        return True
    if path == TRANSFORMER_SCALE:
        # Fixed winding turns and kij preserve the original R and K shape.
        # The winding model reconstructs every mutual from the scaled diagonal.
        field_values = _field_inductances(spec)
        field_values = [float(item)*value for item in field_values]
        spec['coupling_config']['self_inductances_H'] = field_values
        primary_key = 'Lm_forward' if spec['topology'] == 'ACF-FORWARD' else 'L'
        spec[primary_key] = field_values[0]
        return True
    if not path.endswith('.C'):
        return False

    from capacitor_impedance import active_curve
    cap = spec
    for token in path.split('.')[:-1]:
        cap = cap[int(token) if token.isdecimal() else token]
    curve = active_curve(cap)
    if curve is None or value == cap['C']:
        return False

    # Vary only the capacitive reactance in the measured curve. Preserve its
    # measured real impedance and other reactance, and use the same C outside
    # the measured band. The original project's data never change.
    delta = (1/cap['C'] - 1/value)/(2*pi)
    points = []
    for frequency, magnitude, phase in curve['points']:
        angle = radians(phase)
        real = 0. if abs(phase) == 90. else magnitude*cos(angle)
        imaginary = magnitude*sin(angle) + delta/frequency
        points.append([frequency, max(hypot(real, imaginary), 1e-30), degrees(atan2(imaginary, real))])
    curve['points'] = points
    cap['C'] = float(value)
    return True
