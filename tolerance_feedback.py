"""Physical divider setpoint for tolerance cases with a bound compensation network."""

import math


def materialize_feedback_divider(p, compensation_state=None):
    """Freeze the chosen network's physical resistances at its nominal setpoint."""
    from capacitor_banks import normalize
    from compensation_report import compensation_snapshot, network_key
    from cot_settings import active as cot_active
    from isolated_outputs import output_specs
    from voltage_nodes import output_drop

    state = compensation_state if compensation_state is not None else p.get('__comp')
    if (not state or p.get('feedback_mode') == 'PSR-MP6005' or p.get('topology') == 'LLC'
            or cot_active(p)):
        return None
    selected = int(p.get('feedback_output', 1)) - 1 if p.get('outputs') else 0
    try:
        key = network_key(state.get('key') or state.get('topo'))
        if key not in ('opamp3', 'tl431f', 'tl431nf'):
            return None
        specs = output_specs(p) if p.get('outputs') else [normalize(p)]
        rail = specs[selected]
        nominal = abs(float(rail['V_out']))
        op = dict(V_out=nominal, V_feedback=nominal+output_drop(rail))
        parts = compensation_snapshot(p, op, state)['parts']
        upper, lower, ref = (float(parts[name]) for name in ('R1', 'R_lower', 'Vref'))
    except (ValueError, KeyError, IndexError, AttributeError, ArithmeticError, TypeError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in (upper, lower, ref)):
        return None
    divider = dict(upper_ohm=upper, lower_ohm=lower, reference_V=ref, output=selected+1,
                   source=key, nominal_voltage_V=nominal)
    p['tolerance_feedback_divider'] = divider
    return divider


def apply_feedback_divider(p):
    """Apply the sampled hardware divider before solving the unchanged power stage."""
    from voltage_nodes import output_drop

    divider = p.get('tolerance_feedback_divider')
    if divider is None:
        return p
    rail = p['outputs'][divider['output']-1] if p.get('outputs') else p
    upper, lower, ref = (divider[name] for name in ('upper_ohm', 'lower_ohm', 'reference_V'))
    if not all(math.isfinite(value) and value > 0 for value in (upper, lower, ref)):
        raise ValueError('反馈分压电阻和基准电压必须为正有限值。')
    # Keep the same pre-diode sensing arrangement as the wired topology.
    # An absolute setpoint is stored as a magnitude even for inverting stages.
    voltage = ref * (1. + upper/lower) - output_drop(rail)
    if not math.isfinite(voltage) or voltage <= 0.:
        raise ValueError('反馈分压偏差导致输出端口计算设定值无效。')
    rail['V_out'] = p['V_out'] = voltage
    return p
