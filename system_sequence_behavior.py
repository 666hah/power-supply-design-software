"""Declared source protection and resettable load profiles for LTspice.

These are engineering behavioural models, not vendor silicon models. All state
uses capacitors or LTspice logic, never Python state or resettable idt().
"""
from __future__ import annotations

CURRENT_KNEE_RELATIVE = .002


def fmt(value):
    return format(float(value), '.12g')


def protected_source(lines, name, raw, output, row, timer):
    """Finite-R CV/CC characteristic; reject series L in configuration.

    Positive input current flows raw -> output. With sink enabled the negative
    current is limited symmetrically. Hiccup disconnects both directions. There
    is no unmodelled output energy store and no inductive current interruption.

    The CV/CC knee uses a monotone smooth clamp instead of an ideal hard corner.
    Its difference from the ideal clamp is bounded by 0.001 * current ceiling;
    current never exceeds that ceiling. This prevents the zero-incremental-
    conductance corner from stalling the coupled switching network. It is a
    declared source-model approximation, not relaxed simulator tolerances.
    """
    mode = row['protection_mode']
    demand = f'(V({raw})-V({output}))/{fmt(row["resistance_ohm"])}'
    ceiling = fmt(row['current_limit_A'])
    if mode == 'foldback':
        short = row['foldback_short_A']
        ceiling = (f'({fmt(short)}+{fmt(row["current_limit_A"]-short)}*'
                   f'limit(V({output})/max(V({raw}),.001),0,1))')
    knee = f'({fmt(CURRENT_KNEE_RELATIVE)}*({ceiling}))'
    passed = (f'(.5*(sqrt(pow(({demand})+({ceiling}),2)+pow({knee},2))'
              f'-sqrt(pow(({demand})-({ceiling}),2)+pow({knee},2))))')
    if not row['sink_current']:
        passed = f'max({passed},0)'
    fault, active = name+'_fault', name+'_limit'
    magnitude = f'abs({demand})' if row['sink_current'] else f'({demand})'
    lines.append(f'B{name}_LIMIT {active} 0 V=if((V({raw})>.001)&(V({fault})<.5)&({magnitude}>={ceiling}),1,0)')
    if mode == 'hiccup':
        on_age = timer(name+'_LIMIT', active)
        off_age = timer(name+'_FAULT', fault)
        trip, clear = name+'_trip', name+'_clear'
        lines.extend([
            f'B{name}_TRIP {trip} 0 V=if((V({raw})>.001)&(V({active})>.5)&(V({on_age})>={fmt(row["trip_delay_s"])}),1,0)',
            f'B{name}_CLEAR {clear} 0 V=if((V({raw})<=.001)|(V({off_age})>={fmt(row["retry_s"])}),1,0)',
            f'A{name}_FAULT {trip} {clear} 0 0 0 0 {fault} 0 SRFLOP Vhigh=1 Vlow=0 Td=10n Trise=5n Tfall=5n'])
    else:
        lines.append(f'V{name}_FAULT {fault} 0 0')
    lines.append(f'B{name}_PASS {raw} {output} I=if(V({fault})>.5,0,{passed})')
    return dict(limit=active, fault=fault)


def demand_expression(mode, power, reference, voltage, off):
    if mode == 'R':
        return f'max(V({voltage}),0)*{fmt(power/(reference*reference))}'
    if mode == 'I':
        return fmt(power/reference)
    return f'{fmt(power)}/max(V({voltage}),{fmt(off)})'


def staged_load(lines, name, local, row, ready, age, reference, probe):
    """Stages replace total active demand; reset discards logic age, not C.

    Stage transitions interpolate the two I(V) functions at the current voltage.
    A transition never overlaps the next one (validated by configuration).
    """
    clock = f'(V({age})-{fmt(row["delay_s"])})'
    fraction, stage_node, active_current = name+'_fraction', name+'_stage', name+'_active_current'
    stages = row['stages']
    first_ramp = stages[0]['ramp_s']
    fraction_expr = f'limit({clock}/{fmt(first_ramp)},0,1)' if first_ramp else f'if({clock}>=0,1,0)'
    lines.append(f'B{name}_RAMP {fraction} 0 V=if(V({ready})>.5,{fraction_expr},0)')
    previous = '0'
    total = '0'
    index_expression = '0'
    for index, stage in enumerate(stages, 1):
        target = demand_expression(stage['mode'],stage['power_W'],reference,local,row['off_V'])
        elapsed = f'({clock}-{fmt(stage["after_s"])})'
        ramp = f'limit({elapsed}/{fmt(stage["ramp_s"])},0,1)' if stage['ramp_s'] else f'if({elapsed}>=0,1,0)'
        total += f'+({ramp})*(({target})-({previous}))'
        previous = target
        index_expression = f'if({clock}>={fmt(stage["after_s"])},{index},{index_expression})'
    lines.append(f'B{name}_STAGE {stage_node} 0 V=if(V({ready})>.5,{index_expression},0)')
    lines.append(f'B{name}_ACTIVE {active_current} 0 V=if((V({ready})>.5)&(V({local})>0),max({total},0),0)')
    compliance = row['off_V'] or min(1.,reference or 1.)
    standby = f'{fmt(row["off_current_A"])}*limit(V({local})/{fmt(compliance)},0,1)'
    lines.append(f'B{name}_LOAD {local} 0 I=if(V({local})>0,V({active_current})+(1-V({fraction}))*({standby}),0)')
    return dict(stage_probe=probe(stage_node),ready_probe=probe(ready),
                age_probe=probe(age),active_current_probe=probe(active_current))
