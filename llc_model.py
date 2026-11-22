"""Independent switched-periodic and small-signal models of diode LLC converters."""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import SimpleNamespace

import numpy as np
from scipy.integrate import solve_ivp, trapezoid
from scipy.optimize import brentq, root

from llc_settings import VOLTAGE_MODE, HYBRID_MODE, validate


def configuration(p):
    """Return the LLC-specific SI parameters used by calculations and export."""
    return validate({'control_mode': VOLTAGE_MODE} | p)


def fha_gain(frequency, lr, cr, lm, reflected_load, series_r=0.):
    """Fundamental-harmonic tank gain, useful for component selection only."""
    w = 2 * np.pi * np.asarray(frequency)
    zpar = 1 / (1 / reflected_load + 1 / (1j * w * lm))
    return np.abs(zpar / (series_r + 1j*w*lr + 1/(1j*w*cr) + zpar))


@dataclass
class Segment:
    start: float
    end: float
    dense: object
    rectifier: int
    bridge: str


class Tank:
    """Time-domain state equations, with ideal transformer and affine diodes."""

    def __init__(self, p):
        from output_capacitors import build_output_filters
        from voltage_nodes import input_drop, output_drop

        self.c = configuration(p)
        self.p = p
        self.n = float(self.c['N'])
        self.target = float(p['V_out'])
        power = float(p['P_out'])
        self.vin = float(p['V_in']) - input_drop(p)
        if not all(np.isfinite(q) and q > 0 for q in (self.vin, self.n, self.target, power)):
            raise ValueError('LLC 需要正的母线电压、匝比、输出规格和负载功率')
        self.rload = self.target**2 / power
        self.vblock = output_drop(p)
        self.amplitude = self.vin * (.5 if self.c['llc_bridge'] == 'half' else 1.)
        self.l, self.cr, self.lm = (self.c[key] for key in ('llc_lr', 'llc_cr', 'llc_lm'))
        self.vf2 = 2 * float(p.get('Vf_diode', .65))
        self.rrect2 = 2 * self.c['llc_rect_r']
        self.tank_r = self.c['llc_tank_r']
        self.rsw = float(p.get('Rds_on', .05)) * (1 if self.c['llc_bridge'] == 'half' else 2)
        coss = self.c['llc_qoss']/self.vin if self.c['llc_qoss'] else float(p.get('Coss', 0.))
        self.ceq = max(coss, 0.) * (2 if self.c['llc_bridge'] == 'half' else 1)
        self.dead = self.c['llc_dead_time']
        self.filters = build_output_filters([p], [self.rload], [self.target])
        self.a = self.filters.A
        self.b = self.filters.B[:, 0]
        self.cv = self.filters.C[0]
        self.dv = float(self.filters.D[0, 0])
        self.size = 3 + len(self.a)
        rc_rate = max(abs(np.diag(self.a)))
        self.method = 'Radau' if rc_rate/max(self.c['llc_fmin'], 1.) > 100. else 'DOP853'
        self.scale = np.array([max(power / self.amplitude, 1.), self.amplitude,
                               max(power / self.amplitude, 1.)] + [1.] * len(self.a))
        self.sense = self.c['llc_hhc_sense']
        self.ramp = self.c['llc_hhc_ramp']
        self.resonance = 1 / (2 * math.pi * math.sqrt(self.l * self.cr))
        self.antiperiod = np.r_[-np.ones(3), np.ones(len(self.a))]

    def current(self, x, rectifier):
        return self.n * rectifier * (x[0] - x[2])

    def output(self, x, rectifier, load_step=0.):
        # The capacitor coordinates describe the load-side voltage plus the
        # fixed blocking drop. Dynamics see the actual post-diode load.
        inj = self.current(x, rectifier) - load_step
        return float(self.cv @ x[3:self.size] + self.dv * inj)

    def bridge_voltage(self, x, bridge):
        if bridge == 'slew':
            return x[-1]
        return -self.amplitude if bridge == 'low' else self.amplitude

    def voltages(self, x, rectifier, bridge, load_step):
        drive = self.bridge_voltage(x, bridge)
        resistance = self.tank_r + (self.rsw if bridge == 'on' else 0.)
        vl = drive - x[1] - resistance*x[0]
        out = self.output(x, rectifier, load_step)
        if rectifier:
            vp = rectifier*self.n*(out + self.vblock + self.vf2) + self.n**2*self.rrect2*(x[0] - x[2])
        else:
            vp = self.lm / (self.l + self.lm) * vl
        return drive, vp, out, vl

    def derivative(self, x, rectifier, bridge, load_step):
        _, vp, _, vl = self.voltages(x, rectifier, bridge, load_step)
        y = np.empty_like(x)
        y[0], y[1], y[2] = (vl-vp)/self.l, x[0]/self.cr, vp/self.lm
        y[3:self.size] = self.a @ x[3:self.size] + self.b * (self.current(x, rectifier) - load_step)
        y[-1] = -x[0]/self.ceq if bridge == 'slew' else 0.
        return y

    def initial_rectifier(self, x, bridge, load_step):
        diff = x[0] - x[2]
        if abs(diff) > 2e-8:
            return 1 if diff > 0 else -1
        _, vp, out, _ = self.voltages(x, 0, bridge, load_step)
        clamp = self.n * (out + self.vblock + self.vf2)
        return int(vp > clamp+1e-7) - int(vp < -clamp-1e-7)

    def half_map(self, state, duration, *, load_step=0., save=False, threshold=None):
        """Positive half-cycle, starting at the prior polarity turn-off."""
        elapsed = 0.
        x = np.r_[state, -self.amplitude]
        if not self.dead:
            bridge = 'on'
            x[-1] = self.amplitude
        elif not self.ceq:
            bridge = 'high' if x[0] <= 0 else 'low'
        else:
            bridge = 'slew' if x[0] < 0 else 'low'
        rectifier = self.initial_rectifier(x, bridge, load_step)
        segments = []
        residual_v = 2*self.amplitude if not self.dead and self.ceq else (0. if not self.dead else None)
        start_i = x[0]
        for _ in range(36):
            if elapsed >= duration - 1e-13:
                break
            if bridge == 'on':
                stop_time = duration
            else:
                stop_time = min(self.dead, duration)
            events = []

            def add_event(label, fun, direction):
                # A boundary which has just changed state is not an immediate
                # reverse crossing. Progress until there is a new crossing.
                initial_time = elapsed

                def event(t, y):
                    if t < initial_time + 1e-13:
                        return -direction * 1e-10
                    return fun(t, y)
                event.terminal = True
                event.direction = direction
                events.append((label, event))

            if rectifier:
                add_event('rect-open', lambda _t, y: rectifier*(y[0] - y[2]), -1)
            else:
                def diode_gap(y, sign):
                    _, vp, out, _ = self.voltages(y, 0, bridge, load_step)
                    return sign*vp - self.n*(out + self.vblock + self.vf2)
                add_event('rect-pos', lambda _t, y: diode_gap(y, 1), 1)
                add_event('rect-neg', lambda _t, y: diode_gap(y, -1), 1)

            if bridge == 'slew':
                add_event('rail-high', lambda _t, y: y[-1] - self.amplitude, 1)
                add_event('rail-low', lambda _t, y: y[-1] + self.amplitude, -1)
            elif bridge in ('high', 'low') and self.ceq:
                add_event('rail-release', lambda _t, y: y[0], 1 if bridge == 'high' else -1)
            if bridge == 'on' and threshold is not None:
                earliest = .5 / self.c['llc_fmax']
                add_event('hhc', lambda t, y: self.sense*y[1] + self.ramp*max(0., t-self.dead)-threshold
                          if t >= earliest else -max(1e-9, threshold), 1)

            local_bridge, local_rectifier = bridge, rectifier
            result = solve_ivp(lambda _t, y: self.derivative(y, local_rectifier, local_bridge, load_step),
                (elapsed, stop_time), x, method=self.method, dense_output=save,
                events=[e[1] for e in events], rtol=4e-8, atol=2e-9)
            if not result.success:
                raise ValueError('LLC 谐振腔分段积分失败')
            end_time = result.t[-1]
            if save and end_time > elapsed + 1e-15:
                segments.append(Segment(elapsed, end_time, result.sol, rectifier, bridge))
            elapsed = end_time
            x = result.y[:, -1]
            fired = next((label for (label, _), hits in zip(events, result.t_events) if len(hits)), None)
            if fired == 'hhc':
                break
            if fired == 'rect-open':
                x[2] = x[0]
                # With large drive the opposite pair can turn on immediately
                # after the outgoing pair reaches zero. Keep the floating
                # voltage state only when the diode complementarity allows it.
                new_rectifier = self.initial_rectifier(x, bridge, load_step)
                rectifier = new_rectifier if new_rectifier == -rectifier else 0
            elif fired == 'rect-pos':
                rectifier = 1
            elif fired == 'rect-neg':
                rectifier = -1
            elif fired == 'rail-high':
                bridge = 'high'
                x[-1] = self.amplitude
            elif fired == 'rail-low':
                bridge = 'low'
                x[-1] = -self.amplitude
            elif fired == 'rail-release':
                bridge = 'slew'
            if bridge != 'on' and elapsed >= self.dead - 1e-13:
                residual_v = self.amplitude - self.bridge_voltage(x, bridge)
                if not self.ceq:
                    residual_v = 0.
                bridge = 'on'
                x[-1] = self.amplitude
                rectifier = self.initial_rectifier(x, bridge, load_step)
        else:
            raise ValueError('LLC 半周期内换流事件过密，请检查死区、寄生与工作区')
        if residual_v is None:
            residual_v = self.amplitude
        return self.antiperiod*x[:-1], elapsed, segments, dict(
            residual_V=max(0., residual_v), entry_current_A=start_i,
            threshold_V=self.sense*x[1]+self.ramp*max(0., elapsed-self.dead))

    def guess(self, fs):
        w = 2 * math.pi * fs
        equivalent = (8 / math.pi**2) * self.n**2 * self.rload
        zpar = 1 / (1/equivalent + 1/(1j*w*self.lm))
        ir = (4*self.amplitude/math.pi) / (self.tank_r+self.rsw+1j*w*self.l+1/(1j*w*self.cr)+zpar)
        vc = ir/(1j*w*self.cr)
        im = ir*zpar/(1j*w*self.lm)
        estimate = abs(ir*zpar)/(4/math.pi*self.n) - self.vf2 - self.vblock
        return np.r_[ir.imag, vc.imag, im.imag, np.full(len(self.a), max(.05, estimate/self.target))]

    def fixed_point(self, fs, guess=None):
        period = .5 / fs
        seed = self.guess(fs)

        def closure(value):
            mapped, *_ = self.half_map(value*self.scale, period)
            return mapped/self.scale - value

        seeds = [seed, seed * np.r_[1., 1., 1., np.full(self.size-3, .82)]]
        if guess is not None:
            seeds.insert(0, guess)
        for start in seeds:
            try:
                # Match the finite-difference increment to the integration
                # tolerance, especially for grazing rectifier transitions.
                fit = root(closure, start/self.scale, tol=6e-8, options={'eps': 1e-9})
                if np.linalg.norm(closure(fit.x), ord=np.inf) <= 2e-6 and np.min(fit.x[3:]) > 0:
                    return fit.x*self.scale
            except ValueError:
                continue
        raise ValueError(f'LLC {fs / 1e3:.4g} kHz 半周期稳态未收敛')

    def samples(self, segments, duration, *, load_step=0., points=256):
        if not segments:
            raise ValueError('LLC 周期内缺少可用分段')
        regular = np.linspace(0., duration, points+1)
        edges = [g.end for g in segments[:-1]]
        times = np.unique(np.r_[regular, edges, np.asarray(edges)-1e-13])
        times = times[(times >= 0) & (times <= duration)]
        end_times = np.array([g.end for g in segments])
        indices = np.minimum(np.searchsorted(end_times, times, side='right'), len(segments)-1)
        values = np.empty((9, len(times)))
        for index, seg in enumerate(segments):
            mask = indices == index
            if not np.any(mask):
                continue
            state = seg.dense(times[mask])
            for k, column in zip(np.flatnonzero(mask), state.T):
                vdrive, vp, out, _ = self.voltages(column, seg.rectifier, seg.bridge, load_step)
                irect = max(0., self.current(column, seg.rectifier))
                gate = int(seg.bridge == 'on')
                # Subtracting the fixed input DC offset does not alter the
                # full-period input power for the symmetric tank current.
                iin = column[0] * vdrive / self.vin
                values[:, k] = (*column[:3], irect, vdrive, vp, out, iin, gate)
        return times, values

    def mean_output(self, segments, duration, load_step=0.):
        total = 0.
        for seg in segments:
            midpoint = .5 * (seg.start + seg.end)
            radius = .5 * (seg.end - seg.start)
            states = seg.dense(midpoint + radius*_GAUSS_X)
            output = self.cv @ states[3:self.size] + self.dv * (self.current(states, seg.rectifier) - load_step)
            total += radius*float(_GAUSS_W @ output)
        return total/duration


_GAUSS_X, _GAUSS_W = np.polynomial.legendre.leggauss(12)


def solve(p, *, points=320):
    """Solve the periodic steady state at the fixed resistive load.

    The preferred solution is the highest-frequency usable crossing of the
    target voltage. A constrained frequency is reported with actual voltage.
    """
    tank = Tank(p)
    cfg = tank.c
    fmin, fmax = cfg['llc_fmin'], cfg['llc_fmax']
    crossings = {}

    def evaluate(fs):
        if fs not in crossings:
            nearest = min(crossings, key=lambda old: abs(old-fs), default=None)
            start = tank.fixed_point(fs, crossings[nearest][0] if nearest is not None else None)
            mapped, duration, segments, info = tank.half_map(start, .5/fs, save=True)
            average = tank.mean_output(segments, duration)
            crossings[fs] = start, average, duration, segments, info, mapped
        return crossings[fs][1] - tank.target

    # Check high to low to select the descending branch. If an intermediate
    # trial has failed, refine the bracket using the two converged states.
    # Brent still requires converged periodic states for every evaluation.
    previous = None
    fs = None
    failed = []
    frequencies = sorted(set(np.geomspace(fmin, fmax, 13)) |
                         {fmin, fmax, float(np.clip(tank.resonance, fmin, fmax))}, reverse=True)
    for candidate in frequencies:
        try:
            error = evaluate(candidate)
        except ValueError:
            failed.append(float(candidate))
            continue
        if abs(error) < 1e-6:
            fs = candidate
            break
        if previous is not None and previous[1] < 0 < error:
            try:
                fs = brentq(evaluate, candidate, previous[0], xtol=.002)
            except ValueError:
                failed.append(float(candidate))
            else:
                break
        previous = candidate, error
    if not crossings:
        raise ValueError('LLC 频率区间内无收敛工作点，请检查谐振参数和负载')
    regulated = fs is not None
    if not regulated:
        fs = min(crossings, key=lambda f: (abs(crossings[f][1]-tank.target), -f))
    evaluate(fs)
    start, vout, half, segments, info, actual_end = crossings[fs]
    regulated &= abs(vout-tank.target) <= max(.001, tank.target*2e-5)
    notes = []
    usable_loop = regulated and fmin*1.0001 < fs < fmax*.9999
    if failed:
        notes.append('部分搜索频点的周期状态未收敛，缺失频点未参与过零插值。')
    if not regulated:
        notes.append('频率范围内未找到下降增益分支上的稳压点，列出最接近的周期结果。')
    hhc_result = None
    hhc_timing_ok = True
    if cfg['control_mode'] == HYBRID_MODE and regulated:
        hhc_result = tank.half_map(start, .5/fmin, threshold=info['threshold_V'])
        if abs(hhc_result[1]-half)>max(20e-9, half*.003):
            usable_loop = False
            hhc_timing_ok = False
            notes.append('混合滞环在该周期先触及其他阈值或限频边界。')
        # The upward crossing must have positive slew for local linearization.
        crossing_slope = tank.sense*(-actual_end[0])/tank.cr + tank.ramp
        if crossing_slope <= 0:
            usable_loop = False
            hhc_timing_ok = False
            notes.append('混合滞环关断点的比较量斜率非正。')
    threshold_slew = tank.sense*(-actual_end[0])/tank.cr + tank.ramp
    t, y = tank.samples(segments, half, points=max(32, int(points/2)))
    # Document both polarities without interpolation across a gate edge.
    time = np.r_[t[:-1], t+half]
    wave = np.column_stack((y[:, :-1], y * np.array([[-1],[-1],[-1],[1],[-1],[-1],[1],[1],[-1]])))
    if cfg['llc_bridge'] == 'half':
        # In the high rail the DC input supplies the tank, in the low rail it
        # carries no conductive tank current. Equal Coss split the slew current.
        rail = np.where(wave[4] >= tank.amplitude-1e-7, 1.,
                        np.where(wave[4] <= -tank.amplitude+1e-7, 0., .5))
        wave[7] = rail*wave[0]
    else:
        wave[7] = np.where(abs(wave[4]) >= tank.amplitude-1e-7,
                           wave[0]*np.sign(wave[4]), 0.)
    total = 2*half

    def mean(signal):
        return float(trapezoid(signal, t) / half)

    irms = math.sqrt(max(0., mean(y[0]**2)))
    irect_rms = math.sqrt(max(0., mean(y[3]**2)))
    rectified_mean = mean(y[3])
    output_power = mean(y[6]**2)/tank.rload
    conducted_rms_squared = mean(y[0]**2 * (y[8]!=0))
    driver = (2 if cfg['llc_bridge']=='half' else 4)*float(p.get('Qg', 0))*float(p.get('Vgs', 10.))*fs
    loss = dict(tank_copper=tank.tank_r*irms**2,
                switch_conduction=tank.rsw*conducted_rms_squared,
                rectifier=tank.vf2*rectified_mean+tank.rrect2*irect_rms**2,
                output_cap_esr=max(0., mean(y[6]*y[3]) - output_power),
                output_block=tank.vblock*rectified_mean,
                coss_turn_on=.5*tank.ceq*info['residual_V']**2 / half,
                gate_drive=driver)
    loss['input_block'] = (float(p['V_in'])-tank.vin)*max(0., mean(y[4]*y[0])/tank.vin)
    total_loss = sum(loss.values())
    efficiency = output_power/(output_power+total_loss)
    max_current = float(np.max(abs(y[0])))
    protection_hit = bool(cfg['llc_ocp'] and max_current>=cfg['llc_ocp'])
    if protection_hit:
        notes.append('谐振电流达到逐脉冲限流值，稳态为保护动作前的参考波形。')
        usable_loop = False
    needed_charge = tank.ceq*2*tank.amplitude
    available_charge = 0.
    for seg in segments:
        if seg.start >= tank.dead:
            break
        ts = np.linspace(seg.start, min(tank.dead, seg.end), 16)
        available_charge += float(trapezoid(np.maximum(0., -seg.dense(ts)[0]), ts))
    leg_residual = info['residual_V'] * (1. if cfg['llc_bridge']=='half' else .5)
    zvs_limit = max(.5,tank.vin*.005)
    zvs = bool(tank.dead>0 and tank.ceq>0 and leg_residual < zvs_limit)
    phase = -math.degrees(math.atan2(mean(y[0]*np.cos(np.pi*t/half)), mean(y[0]*np.sin(np.pi*t/half))))
    raw_vcr = wave[1] + (tank.amplitude if cfg['llc_bridge']=='half' else 0.)
    on_segment = next(seg for seg in segments if seg.bridge == 'on')
    gate_on_current = float(on_segment.dense(on_segment.start)[0])
    return dict(frequency_Hz=float(fs), period_s=total, regulation_ok=regulated and hhc_timing_ok and not protection_hit,
        setpoint_reached=regulated, loop_valid=usable_loop, output_voltage_V=vout, output_current_A=vout/tank.rload,
        output_power_W=output_power, input_voltage_V=tank.vin, input_current_A=(output_power+total_loss)/float(p['V_in']),
        input_power_W=output_power+total_loss, load_R_ohm=tank.rload, bridge_amplitude_V=tank.amplitude,
        duty=max(0., .5-tank.dead/total), loss_W=loss, efficiency=efficiency, phase=phase, phase_deg=phase,
        v_zvs=leg_residual, zvs_ok=zvs, zvs_voltage_limit_V=zvs_limit, deadtime_entry_current_A=info['entry_current_A'],
        zvs_required_charge_C=needed_charge, zvs_available_charge_C=available_charge,
        protection_hit=protection_hit, mode='LLC-HHC' if cfg['control_mode']==HYBRID_MODE else 'LLC-VCO',
        bridge=cfg['llc_bridge'], control_mode=cfg['control_mode'], f_res_Hz=tank.resonance,
        state_count=tank.size, state_initial=start, v_cap_V=vout+tank.vblock, hhc_threshold_V=info['threshold_V'],
        hhc_turnoff_s=hhc_result[1] if hhc_result else None, hhc_crossing_slew_V_per_s=threshold_slew,
        hhc_timing_ok=hhc_timing_ok,
        residual=float(max(abs(actual_end-start)/tank.scale)), notes=notes,
        time_s=time, i_res_A=wave[0], v_res_V=wave[1], v_cr_V=raw_vcr, i_mag_A=wave[2],
        i_rect_A=wave[3], v_drive_V=wave[4], v_primary_V=wave[5], v_out_V=wave[6],
        i_in_A=wave[7], gate_state=wave[8], ir_peak_A=max_current, ir_rms_A=irms,
        v_cap_wave_V=wave[6]+tank.vblock, i_out_cap_A=wave[3]-wave[6]/tank.rload,
        switch_rms_A=math.sqrt(max(0., conducted_rms_squared*.5)),
        switch_ion_A=gate_on_current, switch_ioff_A=float(-actual_end[0]),
        diode_rms_A=irect_rms/math.sqrt(2.),
        lr_flux_linkage_pp_Wbturn=float(np.ptp(wave[0]))*tank.l,
        mag_flux_linkage_pp_Wbturn=float(np.ptp(wave[2]))*tank.lm,
        im_peak_A=float(np.max(abs(y[2]))), im_rms_A=math.sqrt(max(0., mean(y[2]**2))),
        rectifier_peak_A=float(np.max(y[3])), rectifier_rms_A=irect_rms,
        cr_peak_V=float(np.max(abs(raw_vcr))), cr_rms_V=math.sqrt(max(0., mean(y[1]**2))),
        switch_peak_V=tank.vin, rectifier_reverse_peak_V=float(np.max(abs(y[5])))/tank.n,
        output_ripple_V=float(np.ptp(y[6])))


def load_sweep(p, fractions=(1., .5, .1)):
    """Check the same hardware across continuous-frequency load cases."""
    rows = []
    for fraction in fractions:
        if not math.isfinite(fraction) or not 0 < fraction <= 1:
            raise ValueError('LLC 扫描负载比例须在 0 到 1 之间且大于零')
        case = {'fraction': fraction}
        try:
            result = solve(dict(p, P_out=p['P_out']*fraction), points=128)
            for key in ('frequency_Hz', 'output_voltage_V', 'regulation_ok', 'zvs_ok', 'v_zvs', 'ir_peak_A', 'notes'):
                case[key] = result[key]
        except ValueError as exc:
            case['error'] = str(exc)
        rows.append(case)
    return rows


def _linearized_plant(p, op):
    import control as ct

    if not op['loop_valid']:
        raise ValueError('LLC 当前周期工作点未稳压或已进入限幅，无法计算双向小信号裕度')
    tank = Tank(p)
    fs, steady = op['frequency_Hz'], np.asarray(op['state_initial'])
    half = .5/fs
    hybrid = tank.c['control_mode'] == HYBRID_MODE
    drive = op['hhc_threshold_V'] if hybrid else -fs

    def sample(state, actuation, load_step):
        limit = .5/tank.c['llc_fmin'] if hybrid else -.5/actuation
        after, duration, segments, _ = tank.half_map(state*tank.scale, limit,
            threshold=actuation if hybrid else None, load_step=load_step, save=True)
        output = tank.mean_output(segments, duration, load_step)
        return np.r_[after / tank.scale, output]

    base = np.r_[steady/tank.scale, drive, 0.]
    delta = np.r_[np.full(tank.size, 2e-5), max(.0002*abs(drive), .00015), max(2e-4*op['output_current_A'], 1e-4)]
    jac = np.empty((tank.size+1, tank.size+2))
    for column, step in enumerate(delta):
        high, low = base.copy(), base.copy()
        high[column] += step
        low[column] -= step
        jac[:, column] = (sample(high[:-2], *high[-2:])-sample(low[:-2], *low[-2:]))/(2*step)
    a, b = jac[:-1, :-2], jac[:-1, -2:]
    c, d = jac[-1:, :-2], jac[-1:, -2:]
    identity = np.eye(len(a))
    if np.linalg.cond(identity+a) > 1e9:
        raise ValueError('LLC 采样极点接近 −1，低频等效模型无效')
    radius = float(max(abs(np.linalg.eigvals(a))))
    if radius >= 1.0001:
        raise ValueError('LLC 内部周期映射不稳定，请检查 HHC 斜坡与开关工作区')
    inverse = np.linalg.solve(identity+a, identity)
    gain = 2/half
    full = ct.ss(gain*(a-identity) @ inverse, gain*inverse @ b, 2*c @ inverse, d-c @ inverse @ b)
    return full, radius


def controller_gains(p, op, plant=None, *, fc=None, pm=65.):
    """Use physical voltage error at the controller input in both modes."""
    cfg = configuration(p)
    if fc is None and cfg['llc_ki'] > 0:
        return cfg['llc_kp'], cfg['llc_ki']
    if plant is None:
        plant = _linearized_plant(p, op)[0][0, 0]
    fc_max = op['frequency_Hz']/30
    frequency = min(700., fc_max) if fc is None else float(fc)
    if not 0 < frequency <= fc_max:
        raise ValueError('LLC 目标穿越频率必须大于零并低于实际开关频率的 1/30')
    omega = 2 * np.pi * frequency
    response = complex(plant(1j*omega))
    angle = math.radians(pm-180)-float(np.angle(response))
    if not -np.pi/2 <= angle < 0:
        if fc is not None:
            raise ValueError('LLC 频率与相位目标超出 PI 补偿范围')
        # With insufficient plant lag an integral-only loop already exceeds
        # the phase-margin target at the requested frequency.
        dc = float(np.real(plant(0.)))
        if dc <= 0:
            raise ValueError('LLC 所在工作点控制增益方向不正确')
        if -65. < math.degrees(float(np.angle(response))) <= 0.:
            return 0., omega/abs(response)
        return 0., 2*np.pi*min(60., frequency)/dc
    amp = 1/abs(response)
    return amp*math.cos(angle), -omega*amp*math.sin(angle)


def build_loop(p, op):
    """Linearize the actual switched plant, using the selected comparator."""
    import control as ct

    full, radius = _linearized_plant(p, op)
    plant = full[0, 0]
    kp, ki = controller_gains(p, op, plant)
    compensator = ct.tf([kp, ki], [1., 0.])
    hybrid = op['control_mode'] == HYBRID_MODE
    scope = ('LLC 半周期周期映射线性化，采用双线性变换得到低频等效。'
             '含独立电容 C+ESR、恒阻负载、整流换流与常数 Coss 死区。'
             '混合滞环按电容电压与时基斜坡的实际首次交点求半周期。'
             '限频、限流及整流工作区突变附近以开关扫描波形校核。')
    metadata = dict(kind='llc-periodic-half-cycle', feedback_output=1, experimental=False,
        frequency_limit=op['frequency_Hz']/10, recommended_fc_max=op['frequency_Hz']/30,
        bandwidth_limit_enabled=True, inner_spectral_radius=radius, esr_included=True,
        outputs=[dict(id=1, name='OUT1', voltage=op['output_voltage_V'], current=op['output_current_A'])],
        state_count=plant.nstates, plant_input='hhc_threshold_V' if hybrid else 'negative_frequency_Hz',
        control_structure=op['control_mode'], llc_kp=kp, llc_ki=ki, assumptions=scope)
    plant._loop_metadata = metadata
    plant._load_disturbance = full[0, 1]
    plant._load_response_note = scope
    return (plant, compensator, plant*compensator), SimpleNamespace(model_note=scope, loop_metadata=metadata)
