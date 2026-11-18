"""Closed-loop response to a positive current drawn at the feedback rail."""
import numpy as np

from calculation_scheduler import check_calculation_cancelled


def _closed_loop(plant, compensator):
    """Connect the shared plant states once, with u = -Gc(s) * v."""
    command, load = plant.B[:, :1], plant.B[:, 1:]
    direct_command, direct_load = plant.D[0]
    direct_comp = compensator.D.item()
    denominator = 1.0 + direct_command * direct_comp
    if abs(denominator) < 1e-12:
        raise ValueError('补偿器与功率级的直通项形成奇异闭环。')

    u_plant = -direct_comp * plant.C / denominator
    u_comp = -compensator.C / denominator
    u_load = -direct_comp * direct_load / denominator
    y_plant = plant.C / denominator
    y_comp = direct_command * u_comp
    y_load = direct_load / denominator
    a = np.block([
        [plant.A + command @ u_plant, command @ u_comp],
        [compensator.B @ y_plant, compensator.A + compensator.B @ y_comp],
    ])
    b = np.vstack((load + command * u_load, compensator.B * y_load))
    return a, b[:, 0], np.hstack((y_plant, y_comp))[0], y_load


def _step_samples(a, b, c, d, frequency):
    """Sample exact constant-input transitions on progressively coarser grids."""
    from scipy.linalg import expm, matrix_balance

    if a.size:
        # State equations mix currents, voltages and compensator states with
        # different units. Balance before finding poles and propagating.
        a, scale = matrix_balance(a, permute=False, separate=True)
        weights = scale[0]
        b, c = b / weights, c * weights
        poles = np.linalg.eigvals(a)
        slowest = np.max(poles.real)
        if slowest >= 0:
            raise ValueError('当前平均模型的闭环存在不衰减极点。')
        steady_state = np.linalg.solve(a, -b)
        end = min(max(10 / -slowest, 12 / frequency), 2.0)
        interval = min(end/200, 1/(8*np.max(np.abs(poles))))
    else:
        steady_state = np.zeros(0)
        end, interval = 12/frequency, 1/frequency
    dc = float(c @ steady_state + d)
    # Early samples capture the edge and fast poles. The final segment shows
    # the slow envelope without forcing a uniform sample at the fastest pole.
    segment_ends = np.unique(np.minimum(end, [32*interval, 512*interval, end/8, end]))
    time, response = [0.0], [float(d)]
    state = -steady_state
    for segment_end in segment_ends:
        check_calculation_cancelled()
        segment = np.linspace(time[-1], segment_end, 257)
        propagator = expm(a * (segment[1] - segment[0])) if a.size else a
        for sample in segment[1:]:
            state = propagator @ state
            time.append(float(sample))
            response.append(float(c @ state + dc))
    time, response = np.asarray(time), np.asarray(response)
    if not np.isfinite(dc) or not np.all(np.isfinite(response)):
        raise ValueError('负载响应发生数值溢出。')
    return time, response, dc


def _direction(response, time, initial, final, rated, nominal, dc):
    before = nominal + dc * (initial-rated)
    after = nominal + dc * (final-rated)
    incremental = (final-initial)*response
    voltage = before + incremental
    band = float(max(.001*abs(nominal), .02*np.max(np.abs(incremental))))
    outside = np.flatnonzero(np.abs(voltage-after) > band)
    settling = float(time[outside[-1]+1]) if len(outside) and outside[-1]+1 < len(time) else None
    if not len(outside):
        settling = 0.0
    metrics = dict(min_V=float(min(before, voltage.min())), max_V=float(max(before, voltage.max())),
                   droop_V=float(max(0, -incremental.min())),
                   overshoot_V=float(max(0, incremental.max())),
                   start_voltage_V=float(before), final_voltage_V=float(after),
                   settling_s=settling, settling_band_V=band)
    return np.r_[[before, before], voltage], np.r_[[0, 0], incremental], metrics


def feedback_load_step(p, models, op):
    """Use the signed load port with the same compensator as the Bode view."""
    import control as ct

    check_calculation_cancelled()
    gvc, gc, _ = models
    reason = (getattr(gvc, '_load_response_unavailable_reason', None)
              or getattr(gvc, '_load_response_unavailable', None))
    if reason:
        return dict(available=False, reason=reason)
    selected = int(op.get('feedback_output', p.get('feedback_output', 1)))
    rails = op.get('output_ops') or []
    rail_op = rails[selected-1] if 1 <= selected <= len(rails) else op
    specs = op.get('outputs') or []
    spec = specs[selected-1] if 1 <= selected <= len(specs) else p
    nominal = abs(float(rail_op.get('V_out', 0)))
    specified_voltage = abs(float(spec.get('V_out', 0)))
    specified_power = float(spec.get('P_out', 0))
    rated = specified_power/specified_voltage if specified_voltage > 0 and specified_power > 0 else abs(float(rail_op.get('I_out', 0)))
    frequency = float(op.get('f_sw', p.get('f_sw', 0)))
    if not all(np.isfinite(value) and value > 0 for value in (nominal, rated, frequency)):
        return dict(available=False, reason='本工况缺少有效的反馈路额定电流、端口电压或开关频率。')

    plant = getattr(gvc, '_load_plant', None)
    full = getattr(gvc, '_multi_output_system', None)
    load_model = getattr(gvc, '_load_disturbance', None)
    if full is not None:
        row = selected - 1
        inputs = [0, selected]
        plant = ct.ss(full.A, full.B[:, inputs], full.C[[row]], full.D[np.ix_([row], inputs)])
    elif plant is None and load_model is not None:
        control_plant = ct.ss(gvc)
        if not (np.array_equal(control_plant.A, load_model.A) and np.array_equal(control_plant.C, load_model.C)):
            return dict(available=False, reason='功率级及负载输入没有可用的共同状态。')
        plant = ct.ss(control_plant.A, np.hstack((control_plant.B, load_model.B)),
                      control_plant.C, np.hstack((control_plant.D, load_model.D)))
    if plant is None:
        return dict(available=False, reason='当前环路模型尚未定义该反馈路的独立负载动态。')

    try:
        time, response, dc = _step_samples(*_closed_loop(plant, ct.ss(gc)), frequency)
    except (ValueError, np.linalg.LinAlgError) as error:
        return dict(available=False, reason=str(error))
    low, high = .1*rated, .9*rated
    rise_v, rise_delta, rise = _direction(response, time, low, high, rated, nominal, dc)
    fall_v, fall_delta, fall = _direction(response, time, high, low, rated, nominal, dc)
    time_s = np.r_[[-.12*time[-1], 0], time]
    note = getattr(gvc, '_load_response_note', '') or (
        '沿用环路的耦合功率级模型，其他输出支路保持原工况。' if full is not None else '')
    warning = ''
    if max(rise['droop_V'], rise['overshoot_V'], fall['droop_V'], fall['overshoot_V']) > .2*nominal:
        warning = '电压偏移超过工作点电压的 20%，需用开关模型复核。'
    return dict(available=True, feedback_output=selected, output_voltage_V=nominal,
                rated_current_A=rated, current_low_A=low, current_high_A=high, time_s=time_s,
                rise_voltage_V=rise_v, fall_voltage_V=fall_v,
                rise_delta_V=rise_delta, fall_delta_V=fall_delta, rise=rise, fall=fall,
                notes=note, warning=warning)
