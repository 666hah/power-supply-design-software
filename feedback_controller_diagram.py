"""Vector signal circuits for the controller behaviors used by desktop designs."""

import math

from power_stage import fmt_eng


SIGNAL = '#245b88'
TIMING = '#8c4e24'
DRIVE = '#246f60'


class _SignalCircuit:
    """Use the topology renderer's primitives in module-local coordinates."""

    def __init__(self, schematic, origin, *, mirror_width=None):
        self.s = schematic
        self.ox, self.oy = origin
        self.mirror_width = mirror_width

    def point(self, x, y):
        if self.mirror_width is not None:
            x = self.mirror_width - x
        return x + self.ox, y + self.oy

    def wire(self, *points, color=SIGNAL, **kw):
        self.s.wire(*(self.point(*point) for point in points), color=color, **kw)

    def text(self, x, y, label, **kw):
        kw.setdefault('fontsize', 7.5)
        if self.mirror_width is not None and kw.get('ha') in ('left', 'right'):
            kw['ha'] = 'right' if kw['ha'] == 'left' else 'left'
        self.s.text(*self.point(x, y), label, **kw)

    def node(self, *point):
        self.s.node(*self.point(*point))

    def pin(self, x, y, name, *, right=False, below=False, pad=.23):
        self.s.terminal(*self.point(x, y))
        self.text(x, y + (-pad if below else pad), name, ha='right' if right else 'left',
                  va='top' if below else 'bottom', fontsize=7, color=SIGNAL)
        return x, y

    def frame(self, width, height, title, model):
        self.wire((0, 0), (width, 0), (width, height), (0, height), (0, 0),
                  color='#91a6bb', lw=1)
        self.s.text(self.ox+.52, self.oy+height-.46, title,
                    ha='left', fontsize=8.5, fontweight='bold')
        if model:
            self.s.text(self.ox+width-.52, self.oy+height-.46, model,
                        ha='right', fontsize=7)

    def block(self, x, y, width, caption, *, height=1.02, color=SIGNAL):
        bottom, top, right = y-height/2, y+height/2, x+width
        self.wire((x, bottom), (right, bottom), (right, top), (x, top), (x, bottom), color=color)
        self.text(x+width/2, y, caption, color=color)
        return (x, y), (right, y)

    def wave(self, x, y, width, caption, *, pulse=False):
        self.block(x, y, width, '', height=1.3, color=TIMING)
        edges = [(x+.24, y-.22), (x+.49, y-.22), (x+.49, y+.22), (x+.82, y+.22),
                 (x+.82, y-.22), (x+1.08, y-.22)] if pulse else [
                    (x+.24, y-.24), (x+.64, y+.22), (x+.64, y-.24), (x+1.05, y+.22)]
        self.wire(*edges, color=TIMING, lw=1.1)
        self.text(x+(width+1.12)/2, y, caption, color=TIMING)
        return (x, y), (x+width, y)

    def comparator(self, x, y, label, *, signs=('+', '−'), color=SIGNAL):
        self.wire((x, y-1), (x, y+1), (x+2.12, y), (x, y-1), color=color)
        self.text(x+1., y+1.06, label, va='bottom', color=color)
        self.text(x+.33, y+.49, signs[0], color=color, fontsize=8.5)
        self.text(x+.33, y-.49, signs[1], color=color, fontsize=8.5)
        return (x, y+.49), (x, y-.49), (x+2.12, y)

    def summing(self, x, y, *, horizontal, vertical, signs=('+', '+'), upper=False):
        radius = .63
        steps = tuple(2*math.pi*k/32 for k in range(33))
        self.wire(*((x+radius*math.cos(angle), y+radius*math.sin(angle)) for angle in steps))
        self.text(x, y, 'Σ', fontsize=8.5)
        self.text(x-.93, y+.26, signs[0], fontsize=7)
        direction = 1 if upper else -1
        self.text(x+.25, y+direction*.86, signs[1], fontsize=7)
        self.wire(*horizontal, (x-radius, y))
        self.wire(*vertical, (x, y+direction*radius), color=TIMING)
        return x+radius, y

    def logic(self, x, y, label):
        _, out = self.block(x, y, 1.25, label, height=1.55, color=TIMING)
        return (x, y+.38), (x, y-.38), out

    def latch(self, x, y):
        _, out = self.block(x, y, 2.12, '', height=2.46, color=TIMING)
        self.text(x+.43, y+.73, 'S', color=TIMING)
        self.text(x+.43, y-.73, 'R', color=TIMING)
        self.text(x+1.74, y, 'Q', color=TIMING)
        return (x, y+.73), (x, y-.73), out

    def driver(self, x, y, end_x, q, *, phase=None, negative=False, ground_return=False):
        suffix = f'Q{q}' if phase is None else f'Q{q}_P{phase}'
        return_net = 'PGND' if ground_return else f'VS_{suffix}'
        self.wire((x, y-.43), (x, y+.43), (x+1.42, y), (x, y-.43), color=DRIVE)
        self.text(x+.38, y, '−' if negative else '+', fontsize=8, color=DRIVE)
        self.wire((x+1.42, y), self.pin(end_x, y, f'VG_{suffix}', right=True, pad=.13), color=DRIVE)
        self.wire((x+.51, y-.28), (x+.51, y-.61),
                  self.pin(end_x, y-.61, return_net, right=True, below=True, pad=.13), color=DRIVE)
        return x, y

    def passive(self, x, y, kind, *, vertical=False):
        direction = (0, 1) if vertical else (1, 0)
        points = self.s._part(self.point(x, y), direction, None, kind)
        return tuple((px-self.ox, py-self.oy) for px, py in points)

    def ground(self, x, y, name=None):
        for k, half in enumerate((.30, .20, .10)):
            row = y-.115*k
            self.wire((x-half, row), (x+half, row), lw=1)
        if name:
            self.text(x+.43, y-.12, name, ha='left', fontsize=7)


def _sense(c, y, *, gain):
    start, out = c.block(3.8, y, 3.65, gain, height=1.41)
    for level, name, sign in ((.38, 'CS_RAW', '+'), (-.38, 'CS_RETURN', '−')):
        line = y+level
        c.text(4.13, line, sign, fontsize=7)
        c.wire(c.pin(.65, line, name, below=level < 0), (start[0], line))
    return out


def _fixed_pwm(c, p, solved, command):
    from component_management import primary_mos_role
    from nonisolated import effective, is_enabled, slope as nonisolated_slope

    topology = p.get('topology')
    current = p.get('control_mode') == 'Peak Current Mode'
    clamp = topology == 'ACF-FORWARD'
    variant = bool(p.get('spice_config')) and is_enabled(p)
    qparams = effective(p) if variant else p
    feedforward = variant and not current
    separate_limit = feedforward and p.get('Rs', 0.) > 0.
    clock_y = 8.15 if clamp else 7.22
    frequency = (solved or {}).get('f_sw', p.get('f_sw', 0))
    _, clock = c.wave(12.1, clock_y, 4.02, '振荡器', pulse=True)
    if frequency:
        c.text(14.11, clock_y+.78, fmt_eng(frequency, 'Hz'), color=TIMING)
    trip_hi, trip_lo, trip = c.comparator(13.4, 2.95, '峰流比较器' if current else 'PWM 比较器')
    set_pin, reset_pin, q = c.latch(19.2, 5.45)
    c.wire(clock, (18.45, clock_y), (18.45, set_pin[1]), set_pin, color=TIMING)
    c.wire(c.pin(.65, trip_lo[1], command, below=True), trip_lo)
    if current:
        gain = qparams.get('A_sense', 1.)
        sense = _sense(c, 4.6, gain=f'采样 × {gain:g}')
        slope = nonisolated_slope(qparams) if variant else p.get('ma_slope', 0.)*p.get('Rs', 0.)*gain
        if slope:
            _, ramp = c.wave(3.8, 6.72, 3.65, '补偿斜坡')
            c.text(5.62, 7.62, fmt_eng(slope, 'V/s'), color=TIMING, fontsize=7)
            plus = c.summing(10.35, 4.6, horizontal=(sense,),
                             vertical=(ramp, (10.35, ramp[1])), upper=True)
        else:
            plus = sense
        c.wire(plus, (12.32, plus[1]), (12.32, trip_hi[1]), trip_hi)
    else:
        ramp_label = f'锯齿 {fmt_eng(qparams.get("Vm", 0.), "V")}'
        a, ramp = c.wave(4.45, 4.7, 4.35, ramp_label)
        if feedforward:
            c.wire(c.pin(.65, a[1], 'VIN_BUS'), a, color=TIMING)
        if separate_limit:
            cs_hi, cs_lo, limited = c.comparator(9.2, 7.02, '逐周期限流')
            sense = _sense(c, cs_hi[1], gain='差分采样')
            c.wire(sense, cs_hi)
            threshold = (p.get('spice_config') or {}).get('cs_limit', 0.)
            c.wire(c.pin(7.95, cs_lo[1], fmt_eng(threshold, 'V') if threshold else '限流阈值', below=True), cs_lo)
            c.wire(limited, c.pin(11.67, limited[1], 'CS_TRIP', right=True, below=True), color=TIMING)
        c.wire(ramp, (12.32, 4.7), (12.32, trip_hi[1]), trip_hi)
        c.wire((14.1, clock_y-.65), (14.1, 5.95), (6.62, 5.95), (6.62, 5.35), color=TIMING)
    first, second, reset = c.logic(17.05, 3.86, '≥1')
    c.wire(trip, (16.1, trip[1]), (16.1, second[1]), second, color=TIMING)
    c.wire((15.45, clock_y-.65), (15.45, first[1]), first, color=TIMING)
    c.text(15.7, 5.04, 'Dmax', ha='left', fontsize=7, color=TIMING)
    if separate_limit:
        c.wire(c.pin(17.68, 2.46, 'CS_TRIP', below=True), (17.68, 3.085), color=TIMING)
    c.wire(reset, (18.7, reset[1]), (18.7, reset_pin[1]), reset_pin, color=TIMING)
    if clamp:
        _, split = c.block(22.2, q[1], 3.15, '互锁／死区', height=2.28, color=TIMING)
        time = ((p.get('spice_config') or {}).get('acf_dead_ns') or 0.)*1e-9 or p.get('forward_dead_time', 0.)
        c.text(23.775, 6.89, fmt_eng(time, 's'), fontsize=7, color=TIMING)
        c.wire(q, (22.2, q[1]), color=TIMING)
        main = c.driver(26.7, 7.2, 30.8, 1, ground_return=True)
        clamp_out = c.driver(26.7, 3.5, 30.8, 2, negative=True, ground_return=True)
        for offset, gate, label in ((.64, main, '主'), (-.64, clamp_out, '钳')):
            y = q[1]+offset
            c.text(25.07, y, label, ha='right', color=TIMING)
            c.wire((split[0], y), (26, y), (26, gate[1]), gate, color=DRIVE)
    else:
        driver = c.driver(22.45, q[1], 26.55, 1, negative='P-MOS' in primary_mos_role(p),
                          ground_return=topology == 'FLYBACK')
        c.wire(q, driver, color=DRIVE)


def _qr(c, p, command):
    from qr_spice_settings import QR_SETTINGS

    settings = p.get('spice_config') or {}
    r_zcd = settings.get('qr_zcd_r', QR_SETTINGS['qr_zcd_r'][0])
    c_zcd = settings.get('qr_zcd_c_pf', QR_SETTINGS['qr_zcd_c_pf'][0])*1e-12
    arm = settings.get('qr_zcd_arm_v', QR_SETTINGS['qr_zcd_arm_v'][0])
    trigger = settings.get('qr_zcd_trigger_v', QR_SETTINGS['qr_zcd_trigger_v'][0])
    raw_hi, raw_lo, replica = c.comparator(4.5, 8.2, '绕组等效取样')
    c.wire(c.pin(.65, raw_hi[1], 'ZCD_RAW+'), raw_hi)
    c.wire(c.pin(.65, raw_lo[1], 'ZCD_RAW−', below=True), raw_lo)
    rz_left, rz_right = c.passive(7.75, 8.2, 'resistor')
    c.wire(replica, rz_left)
    c.text(7.75, 8.83, f'Rz {fmt_eng(r_zcd, "Ω")}', color=SIGNAL)
    zcd = (8.8, 8.2)
    low, high = c.passive(8.8, 7.32, 'capacitor', vertical=True)
    c.wire(rz_right, zcd, high)
    c.node(*zcd)
    c.ground(*low)
    c.text(8.42, 7.3, f'Cz {fmt_eng(c_zcd, "F")}', ha='right')
    z_hi, z_lo, fall = c.comparator(10.65, 7.71, '迟滞下降沿', signs=('−', '+'))
    c.wire(zcd, z_hi)
    c.text(10.0, 8.56, 'ZCD', color=SIGNAL)
    c.wire(c.pin(9.18, z_lo[1], '阈值', below=True), z_lo)
    c.text(13.05, 9.3, f'预备 {arm:g} V / 触发 {trigger:g} V', ha='left', color=TIMING, fontsize=7)
    start, window = c.block(13.4, fall[1], 3.52, '关断消隐／延时', color=TIMING)
    c.wire(fall, start, color=TIMING)
    _, restart = c.wave(13.4, 6.15, 3.52, '启动定时', pulse=True)
    upper, lower, pulse = c.logic(17.8, 7.05, '≥1')
    c.wire(window, (17.36, window[1]), (17.36, upper[1]), upper, color=TIMING)
    c.wire(restart, (17.36, restart[1]), (17.36, lower[1]), lower, color=TIMING)
    en_upper, en_lower, permit = c.logic(20.15, 6.67, '&')
    c.wire(pulse, en_upper, color=TIMING)
    run = c.pin(17.42, 5.04, 'RUN', below=True)
    c.wire(run, (19.54, run[1]), (19.54, en_lower[1]), en_lower, color=TIMING)
    sense = _sense(c, 4.25, gain=f'滤波 × {p.get("A_sense", 1):g}')
    pwm_hi, pwm_lo, trip = c.comparator(13.45, 3.35, '峰流比较器')
    c.wire(sense, (11.75, sense[1]), (11.75, pwm_hi[1]), pwm_hi)
    cmd, limit = c.block(4.1, pwm_lo[1], 3.45, '电流命令限幅')
    c.wire(c.pin(.65, pwm_lo[1], command, below=True), cmd)
    c.wire(limit, pwm_lo)
    c.wire((9.55, pwm_lo[1]), (9.55, 5.55), (13.08, 5.55),
           (13.08, 7.42), (13.4, 7.42), color=TIMING)
    c.node(9.55, pwm_lo[1])
    c.text(11.55, 5.82, 'COMP → 消隐时间', fontsize=7, color=TIMING)
    start, blanked = c.block(16.4, trip[1], 2.28, 'LEB', color=TIMING)
    c.wire(trip, start, color=TIMING)
    _, max_on = c.wave(16.4, 1.69, 3.45, '最长导通', pulse=True)
    first, second, reset = c.logic(20.37, 3.18, '≥1')
    c.wire(blanked, (19.67, blanked[1]), (19.67, first[1]), first, color=TIMING)
    c.wire(max_on, (20.01, max_on[1]), (20.01, second[1]), second, color=TIMING)
    set_pin, reset_pin, q = c.latch(22.36, 5.32)
    c.wire(permit, (21.89, permit[1]), (21.89, set_pin[1]), set_pin, color=TIMING)
    c.wire(reset, (21.99, reset[1]), (21.99, reset_pin[1]), reset_pin, color=TIMING)
    c.wire(q, c.driver(25.15, q[1], 29.5, 1, ground_return=True), color=DRIVE)


def _psr(c, solved):
    fb_y = 8.53
    sample = c.pin(.65, fb_y, 'FB_AUX')
    c.wire(sample, (4.28, fb_y))
    for x in (4.32, 5.92):
        c.s.terminal(*c.point(x, fb_y))
    c.wire((4.42, fb_y+.035), (5.7, fb_y+.34))
    c.wire((6.0, fb_y), (6.72, fb_y))
    low, high = c.passive(6.72, 7.49, 'capacitor', vertical=True)
    c.wire((6.72, fb_y), high)
    c.node(6.72, fb_y)
    c.ground(*low, 'PGND')
    c.text(6.33, 7.52, 'Ch', ha='right')
    _, window = c.wave(1.65, 10.1, 4.72, '退磁采样窗', pulse=True)
    c.wire(window, (6.78, window[1]), (6.78, 9.47), (5.1, 9.47), (5.1, 8.96),
           color=TIMING, ls='--')
    c.text(11.64, 10.10, '关断后消隐约 300 ns', fontsize=7, color=TIMING)
    hi, lo, error = c.comparator(9.45, 8.36, '跨导误差放大器')
    c.wire((6.72, fb_y), (8.63, fb_y), (8.63, lo[1]), lo)
    c.wire(c.pin(7.73, hi[1], '2 V'), hi)
    c.wire(error, c.pin(14.76, error[1], 'COMP', right=True))
    c.text(13.09, 7.91, 'gₘ ≈ 590 µS', color=SIGNAL)

    point = (solved or {}).get('psr') or {}
    region = (solved or {}).get('regulation_region', point.get('region'))
    pfm = region in ('PFM', 'PFM-estimate')
    _, clock = c.wave(15.54, 8.52, 5.23, '轻载降频定时' if pfm else '250 kHz 振荡器', pulse=True)
    c.text(18.158, 9.32, 'MODE 悬空', color=TIMING, fontsize=7)
    if pfm:
        c.text(14.72, 2.03, '轻载近似：峰值采样约 36 mV', color=TIMING, fontsize=7)
    amp, sensed = c.block(3.45, 4.42, 4.12, '峰值采样 × 11')
    c.wire(c.pin(.65, amp[1], 'SENSE'), amp)
    upper, lower, trip = c.comparator(10.16, 3.93, '电流比较器')
    c.wire(sensed, upper)
    command_caption = 'PFM 峰值阈值' if pfm else 'COMP'
    c.wire(c.pin(.65, lower[1], command_caption, below=True), lower)
    a, b = c.block(13.15, trip[1], 4.3, '开通消隐／限流', color=TIMING)
    c.wire(trip, a, color=TIMING)
    first, second, reset = c.logic(18.65, 4.48, '≥1')
    c.wire(b, (17.94, b[1]), (17.94, second[1]), second, color=TIMING)
    c.wire((19.55, 7.87), (19.55, 6.8), (18.15, 6.8), (18.15, first[1]), first, color=TIMING)
    c.text(17.45, 6.56, 'Dmax', fontsize=7, color=TIMING)
    set_pin, reset_pin, q = c.latch(22.05, 5.71)
    c.wire(clock, (21.58, clock[1]), (21.58, set_pin[1]), set_pin, color=TIMING)
    c.wire(reset, (20.83, reset[1]), (20.83, reset_pin[1]), reset_pin, color=TIMING)
    c.wire(q, c.driver(25.11, q[1], 29.5, 1, ground_return=True), color=DRIVE)
    c.text(.66, 1.07, '原边辅助反馈 · 采样与保持按平均模型等效', ha='left', fontsize=7)


def _cot_phase(c, phase, y, config, currents):
    balance = config['balance_gain_v_per_a'] > 0
    limit = config['phase_limit_A'] > 0
    if currents:
        hardware = config['phase_parameters'][phase-1]
        adjusted = hardware['sense_gain'] != 1. or hardware['sense_offset_A'] != 0.
        start, sense = c.block(3.8, y-.49, 3.65, '电流增益／零偏' if adjusted else '电感电流取样')
        c.wire(c.pin(.65, start[1], f'IS_P{phase}'), start)
        c.wire(sense, c.pin(8.75, sense[1], f'I_P{phase}', right=True, below=True))
        if balance:
            hi, lo, delta = c.comparator(10.05, y, '均流差值')
            c.wire(c.pin(7.72, hi[1], 'I_AVG'), hi)
            c.wire((8.75, sense[1]), lo)
            left, trim = c.block(13, y, 4.25, '低通／限幅 ΔD')
            c.wire(delta, left)
            c.wire(trim, (20.25, y))
        if limit:
            a, b = c.block(12.5, y-1.45, 4.75, '相限流比较／复位', color=TIMING)
            c.wire((8.75, sense[1]), (9.10, sense[1]), (9.10, a[1]), a)
            c.wire(b, (19.59, b[1]), (19.59, y-.54), (20.25, y-.54), color=TIMING)
    edge, pulse = c.wave(20.25, y, 4.0, f'单稳态 {phase}', pulse=True)
    c.wire(c.pin(17.88, y+.46, f'TRIG_P{phase}'), (edge[0], y+.46), color=TIMING)
    ton_pin = c.pin(21.8, y+1.63, 'TON_BASE')
    c.wire(ton_pin, (21.8, y+.65), color=TIMING)
    pcm = config['light_load'] == 'diode_emulation'
    left, _ = c.block(25, y, 3.43, '过零停低侧' if pcm else '高／低侧互锁', height=2.77, color=TIMING)
    c.wire(pulse, left, color=TIMING)
    if pcm:
        c.wire(c.pin(22.35, y-.94, f'I_P{phase}', below=True), (25, y-.94), color=TIMING)
    for gate, dy in ((1, 1.1), (2, -1.1)):
        driver = c.driver(29.05, y+dy, 33.75, gate, phase=phase)
        c.wire((28.43, y+dy), driver, color=DRIVE)


def _cot(c, p, solved, command, config, phases):
    balance = config['balance_gain_v_per_a'] > 0
    feedback = config['model'] == 'current_feedback'
    currents = balance or feedback or config['phase_limit_A'] > 0 or config['light_load'] == 'diode_emulation'
    top = 6.57 + (phases-1)*4.3
    y = top + 3.65
    hi, lo, err = c.comparator(4.45, y, '电压误差')
    c.wire(c.pin(.65, hi[1], 'VREF'), hi)
    c.wire(c.pin(.65, lo[1], command, below=True), lo)
    a, pi = c.block(7.45, y, 3.55, '电压 PI → Hz')
    c.wire(err, a)
    label = 'I_P1' if phases == 1 else f'I_P1… I_P{phases}'
    if balance:
        a, average = c.block(5.15, y-3.4, 3.5, 'Σ I / 活动相数')
        c.wire(c.pin(.65, a[1], label), a)
        c.wire(average, c.pin(10.27, average[1], 'I_AVG', right=True))
    if feedback:
        feedback_y = y-1.92
        c.wire(c.pin(.65, feedback_y, label), (5.15, feedback_y))
        _, trim = c.block(5.15, feedback_y, 5.45, 'Σ I → 低通 × 电流增益')
        pi = c.summing(12.35, y, horizontal=(pi,), vertical=(trim, (12.35, trim[1])), signs=('+', '−'))
    a, cadence = c.block(13.42, y, 4.15, '最短关断限频', color=TIMING)
    _, triggers = c.wave(18.25, y, 5.46, '相位累加／轮转', pulse=True)
    c.wire(pi, a)
    c.wire(cadence, (18.25, y), color=TIMING)
    # One vector of pulses, with scalar pins on each channel below.
    phase_end = 'TRIG_P1' if phases == 1 else f'TRIG_P1… TRIG_P{phases}'
    c.wire(triggers, c.pin(32.95, y, phase_end, right=True), color=TIMING)
    for phase in range(1, phases+1):
        _cot_phase(c, phase, 2.65+(phases-phase)*4.3, config, currents)
    manual = p.get('cot_ton_s', 0.)
    timer = '固定 Ton' if manual else 'VIN 前馈 Ton'
    a, ton = c.block(20.25, y-2.04, 4.62, timer, color=TIMING)
    if not manual:
        c.wire(c.pin(16.80, a[1], 'VIN_BUS'), a, color=TIMING)
    c.wire(ton, c.pin(30.68, ton[1], 'TON_BASE', right=True), color=TIMING)
    conditions = (solved or {}).get('cot') or {}
    cap_time = conditions.get('base_ton_s', conditions.get('ton_s', manual))
    if cap_time:
        c.text(22.56, y-2.74, fmt_eng(cap_time, 's'), fontweight='normal', color=TIMING, fontsize=7)


def _llc_command(c, command, *, hybrid):
    y = 9.75
    if command == 'V_OPTO':
        a, control = c.block(4.4, y, 6.05, '光耦 → 等效调制指令')
        c.wire(c.pin(.65, y, command), a)
    else:
        hi, lo, err = c.comparator(4.2, y, '电压误差')
        c.wire(c.pin(.65, hi[1], 'VREF'), hi)
        c.wire(c.pin(.65, lo[1], command, below=True), lo)
        a, control = c.block(7.18, y, 3.27, '电压 PI')
        c.wire(err, a)
    caption = '基准 + 调制量' if hybrid else '偏置 − 调制量'
    a, adjusted = c.block(11.43, y, 4.35, caption)
    c.wire(control, a)
    return adjusted


def _llc_bridge_drive(c, p, source, *, hybrid):
    full = p.get('llc_bridge') == 'full'
    dead = p.get('llc_dead_time', 0.)
    a, _ = c.block(23.88, 5.8, 3.52, '互锁／死区', height=4.25, color=TIMING)
    c.wire(source, (23.5, source[1]), (23.5, a[1]), a, color=TIMING)
    if dead:
        c.text(25.64, 8.2, fmt_eng(dead, 's'), color=TIMING, fontsize=7)
    if p.get('llc_ocp', 0.) > 0.:
        c.wire(c.pin(21.06, 4.24, 'FAULT', below=True), (23.88, 4.24), color=TIMING)
    modes = ((7.04, 'Qφ' if hybrid else 'φ+', ((1, 8.36), (4, 6.38))),
             (4.56, 'Q̅φ' if hybrid else 'φ−', ((2, 4.23), (3, 2.25))))
    for split_y, label, outputs in modes:
        c.text(26.65, split_y, label, fontsize=7, color=TIMING, ha='right')
        xpos = 27.96
        split = (xpos, split_y)
        c.wire((27.4, split_y), split, color=DRIVE)
        for q, y in outputs if full else outputs[:1]:
            out = c.driver(28.69, y, 33.75, q)
            c.wire(split, (xpos, y), out, color=DRIVE)
        if full:
            c.node(*split)


def _llc(c, p, command, *, hybrid):
    adjusted = _llc_command(c, command, hybrid=hybrid)
    ocp = p.get('llc_ocp', 0.)
    if ocp > 0.:
        hi, lo, trip = c.comparator(4.1, 1.64, '谐振过流比较')
        _, current = c.block(2.05, hi[1], 1.43, '|iLr|')
        c.wire(c.pin(.65, hi[1], 'I_LR'), (2.05, hi[1]))
        c.wire(current, hi)
        c.wire(c.pin(.65, lo[1], fmt_eng(ocp, 'A'), below=True), lo)
        a, fault = c.block(6.49, trip[1], 2.27, '故障锁存', color=TIMING)
        c.wire(trip, a, color=TIMING)
        c.wire(fault, c.pin(8.88, trip[1], 'FAULT', right=True, below=True), color=TIMING)
    if not hybrid:
        a, vco = c.wave(16.7, adjusted[1], 4.54, 'VCO 限频')
        c.wire(adjusted, a)
        fmin, fmax = p.get('llc_fmin', 0.), p.get('llc_fmax', 0.)
        caption = f'{fmt_eng(fmin, "Hz")}–{fmt_eng(fmax, "Hz")}'
        c.text(18.97, vco[1]-.97, caption, color=TIMING, fontsize=7)
        _llc_bridge_drive(c, p, vco, hybrid=False)
        return
    c.wire(adjusted, c.pin(18.43, adjusted[1], 'V_CTRL', right=True))
    hi, lo, sensed = c.comparator(4.52, 5.08, 'Cr 差分取样')
    c.wire(c.pin(.65, hi[1], 'V_CR+'), hi)
    c.wire(c.pin(.65, lo[1], 'V_CR−', below=True), lo)
    sense_a, sense_b = c.block(7.35, sensed[1], 3.65, '减中心值 × 增益')
    c.wire(sensed, sense_a)
    latch_s, latch_r, q = c.latch(21.18, 5.79)
    for y, ramp_y, sign, target in ((6.81, 8.38, '−', latch_s), (3.35, 1.35, '+', latch_r)):
        _, ramp = c.wave(9.17, ramp_y, 3.46, '半周斜坡')
        b = sense_b[0]+.4
        a, sign_out = c.block(11.56, y, 1.13, sign)
        c.wire(sense_b, (b, sense_b[1]), (b, y), a)
        plus = c.summing(13.72, y, horizontal=(sign_out,),
                         vertical=(ramp, (13.72, ramp[1])), upper=ramp_y > y)
        cmp_hi, cmp_lo, tripped = c.comparator(15.27, y-.49, '换相比较')
        c.wire(plus, cmp_hi)
        c.wire(c.pin(13.05, cmp_lo[1], 'V_CTRL', below=True), cmp_lo)
        a, limited = c.block(17.79, tripped[1], 2.75, 'Tmin／Tmax', color=TIMING)
        c.wire(tripped, a, color=TIMING)
        c.wire(limited, (20.82, limited[1]), (20.82, target[1]), target, color=TIMING)
    c.node(11.4, sense_b[1])
    c.text(19.36, 8.27, '半周时间窗', color=TIMING, fontsize=7)
    _llc_bridge_drive(c, p, q, hybrid=True)


def draw_controller_circuit(s, p, solved=None, *, origin=(0, 0), command_net='COMP', top_aligned=False):
    """Append an electrical signal circuit and return its local width and height.

    ``origin`` specifies the bottom-left corner or the top-left corner when
    ``top_aligned`` is true. Open terminals with matching names connect to the
    power, sensing or feedback circuit. The caller supplies an unexpanded
    schematic for this module's coordinates.
    """
    from component_management import controller_reference
    from cot_settings import active as cot_active, configuration
    from llc_settings import HYBRID_MODE, effective

    topology = p.get('topology')
    psr = p.get('feedback_mode') == 'PSR-MP6005'
    managed = controller_reference(p)
    ref = 'U_PSR' if psr else managed['ref'] if managed else None
    item = ((p.get('component_management') or {}).get('items') or {}).get('U_CTRL') or {}
    model = str(item.get('model') or '').strip()[:29]
    if psr:
        width, height, title = 30.25, 11.65, 'MP6005 · 原边采样与 PWM/PFM'
        model = ''
        render = lambda: _psr(c, solved)
    elif cot_active(p):
        phases = int(p.get('buck_phases', 1))
        config = configuration(p)
        width, height, title = 34.5, 12.9+(phases-1)*4.3, f'COT · {phases} 相同步 Buck'
        render = lambda: _cot(c, p, solved, command_net, config, phases)
    elif topology == 'LLC':
        hybrid = p.get('control_mode') == HYBRID_MODE
        width, height = 34.5, 11.72
        title = 'LLC · 混合滞环 HHC' if hybrid else 'LLC · 电压变频 VCO'
        render = lambda: _llc(c, effective(p), command_net, hybrid=hybrid)
    elif topology == 'QR-FLYBACK':
        width, height, title = 30.25, 10.65, '准谐振 · ZCD 置位与峰流关断'
        model = 'L6565 行为参考'+(f' / {model}' if model and 'L6565' not in model.upper() else '')
        render = lambda: _qr(c, p, command_net)
    else:
        clamp = topology == 'ACF-FORWARD'
        width, height = (31.6, 10.18) if clamp else (27.25, 9.04)
        mode = '峰值电流 PWM' if p.get('control_mode') == 'Peak Current Mode' else '电压模式 PWM'
        title = f'有源钳位正激 · {mode}' if clamp else mode
        render = lambda: _fixed_pwm(c, p, solved, command_net)
    x, y = origin
    c = _SignalCircuit(s, (x, y-height if top_aligned else y))
    with s.mark(ref):
        c.frame(width, height, f'{ref} · {title}' if ref else title, model)
        render()
    return width, height


def _block_functions(p, solved):
    from cot_settings import active as cot_active, configuration
    from llc_settings import HYBRID_MODE

    topology = p.get('topology')
    psr = p.get('feedback_mode') == 'PSR-MP6005'
    if psr:
        point = (solved or {}).get('psr') or {}
        region = (solved or {}).get('regulation_region', point.get('region'))
        timing = 'PFM 轻载降频' if region in ('PFM', 'PFM-estimate') else 'PWM 峰流关断'
        return ('原边采样', ('退磁采样', '误差放大', timing),
                ((2, '峰值采样', ('SENSE',)),), (('VG_Q1', 'GATE'),))
    if cot_active(p):
        phases = int(p.get('buck_phases', 1))
        config = configuration(p)
        timing = '固定导通定时' if p.get('cot_ton_s') else '导通定时'
        logic = ('电压误差 PI', timing, '相位轮转') if phases > 1 else ('电压误差 PI', timing)
        aux = []
        if not p.get('cot_ton_s'):
            aux.append((1, '输入前馈', ('VIN_BUS',)))
        if config['model'] == 'current_feedback':
            aux.append((0, '总电流反馈', ()))
        gates = tuple((f'VG_Q{q}_P{phase}', f'{name}{phase}')
                      for phase in range(phases, 0, -1) for q, name in ((2, 'GL'), (1, 'GH')))
        return f'{phases} 相同步 Buck COT', logic, aux, gates
    if topology == 'LLC':
        bridge = p.get('llc_bridge') == 'full'
        hybrid = p.get('control_mode') == HYBRID_MODE
        stages = ('反馈调制量', '换相比较' if hybrid else 'VCO 限频', '互锁／死区')
        aux = [(1, 'Cr 采样／斜坡', ('V_CR+', 'V_CR−'))] if hybrid else []
        if p.get('llc_ocp', 0.) > 0.:
            aux.append((2, '谐振过流', ('I_LR',)))
        labels = ('GH_A', 'GL_A', 'GH_B', 'GL_B') if bridge else ('HO', 'LO')
        return ('LLC 混合滞环' if hybrid else 'LLC 电压变频'), stages, aux, tuple(
            (f'VG_Q{q}', label) for q, label in enumerate(labels, 1))
    if topology == 'QR-FLYBACK':
        return ('准谐振峰流控制', ('峰流比较器', 'SR 锁存'),
                ((0, '电流采样／消隐', ('CS_RAW', 'CS_RETURN')),
                 (1, 'ZCD 谷底触发', ('ZCD_RAW+', 'ZCD_RAW−'))), (('VG_Q1', 'GATE'),))
    current = p.get('control_mode') == 'Peak Current Mode'
    title = '峰值电流 PWM' if current else '电压模式 PWM'
    # Both fixed-frequency paths retain the clock; the voltage-mode ramp is
    # generated from it while peak-current mode uses the sensed current.
    logic = ('峰流比较器' if current else 'PWM 比较器', 'PWM 锁存')
    aux = [(1, '振荡器', ())]
    if current:
        aux.insert(0, (0, '采样／补偿斜坡', ('CS_RAW', 'CS_RETURN')))
    else:
        from nonisolated import is_enabled
        feedforward = bool(p.get('spice_config')) and is_enabled(p)
        aux.insert(0, (0, '输入前馈锯齿' if feedforward else '锯齿斜坡',
                       ('VIN_BUS',) if feedforward else ()))
    if topology == 'ACF-FORWARD':
        return f'有源钳位正激 · {title}', (*logic, '互锁／死区'), aux, (
            ('VG_Q1', 'GATE'), ('VG_Q2', 'AUXG'))
    return title, logic, aux, (('VG_Q1', 'GATE'),)


def draw_controller_block(s, p, solved=None, *, origin=(0, 0), ports=None, command_label='COMP'):
    """Draw an abbreviated controller and expose its physical routing anchors.

    ``origin`` is the absolute top-left position. Pass a dictionary for the
    right input, left gate outputs, bottom sensing and optional PSR COMP pin.
    Output keys use the design's MOS gate names, not the drawn chip labels.
    """
    from component_management import controller_reference

    title, functions, auxiliary, gates = _block_functions(p, solved)
    psr = p.get('feedback_mode') == 'PSR-MP6005'
    managed = controller_reference(p)
    ref = 'U_PSR' if psr else managed['ref'] if managed else None
    item = ((p.get('component_management') or {}).get('items') or {}).get('U_CTRL') or {}
    model = str(item.get('model') or '').split(' · ', 1)[0].strip()
    if len(model) > 23:
        model = model[:22]+'…'
    if psr:
        model = 'MP6005'
    elif p.get('topology') == 'QR-FLYBACK' and not model:
        model = 'L6565'

    stage_width, pitch = 5.65, 6.45
    stage_x = [2.05 + i*pitch for i in range(len(functions))]
    driver_x = stage_x[-1] + pitch
    width = driver_x + 7.75
    height = max(10., 4.15 + (len(gates)-1)*1.0)
    x, y = origin
    c = _SignalCircuit(s, (x, y-height), mirror_width=width)
    signal_y = height - 2.38
    gate_y = [signal_y - i for i in range(len(gates))]
    input_point = c.point(0, signal_y)
    sensor_points, gate_points = {}, {}

    with s.mark(ref):
        c.frame(width, height, f'{ref} · {title}' if ref else title, model)
        incoming = c.pin(0, signal_y, command_label, pad=.21)
        compensation_tap = None
        for index, (left, caption) in enumerate(zip(stage_x, functions)):
            stage_color = SIGNAL if index == 0 else TIMING
            begin, output = c.block(left, signal_y, stage_width, caption, height=1.22, color=stage_color)
            c.wire(incoming, begin, color=stage_color)
            incoming = output
            if psr and index == 1:
                compensation_tap = (output[0] + .34, output[1])

        if p.get('topology') == 'QR-FLYBACK':
            latch_x = stage_x[1]
            c.text(latch_x+.27, signal_y+.2, 'R', ha='left', color=TIMING, fontsize=6.5)
            c.text(latch_x+stage_width/2+.18, signal_y-.83, 'S',
                   ha='left', color=TIMING, fontsize=6.5)

        aux_y = signal_y - 2.7
        # Keep external sensor wiring outside the main command rail.
        for index, caption, names in auxiliary:
            left = stage_x[index]
            center = left + stage_width/2
            c.block(left, aux_y, stage_width, caption, height=1.12, color=TIMING)
            c.wire((center, aux_y+.56), (center, signal_y-.61), color=TIMING)
            for i, name in enumerate(names):
                pin_x = center + (i-(len(names)-1)/2)*2.8
                if psr:
                    point = c.pin(0, aux_y, name, below=True)
                    c.wire(point, (left, aux_y))
                else:
                    point = c.pin(pin_x, 0, name, pad=.17)
                    c.wire(point, (pin_x, aux_y-.56))
                sensor_points[name] = c.point(*point)

        if compensation_tap is not None:
            tap_x, tap_y = compensation_tap
            comp_y = signal_y - 1.22
            point = c.pin(0, comp_y, 'COMP', pad=.17)
            c.wire(point, (tap_x, comp_y), compensation_tap)
            c.node(tap_x, tap_y)
            if ports is not None:
                ports['psr_comp'] = c.point(*point)

        driver_width = 4.2
        center = (gate_y[0] + gate_y[-1])/2
        c.block(driver_x, center, driver_width, '栅极驱动',
                height=max(1.22, gate_y[0]-gate_y[-1]+1.22), color=DRIVE)
        c.wire(incoming, (driver_x, signal_y), color=DRIVE)
        for (gate, label), level in zip(gates, gate_y):
            point = c.pin(width, level, label, right=True, pad=.17)
            c.wire((driver_x+driver_width, level), point, color=DRIVE)
            gate_points[gate] = c.point(*point)

    if ports is not None:
        ports.update(input=input_point, gates=gate_points, sensors=sensor_points)
    return x, x + width, y - height, y
