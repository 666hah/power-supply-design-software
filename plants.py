"""Small-signal (control-to-output) models for the loop-design tab.

Buck / Boost / Buck-Boost / Flyback: CCM average models, voltage mode and
peak-current mode, following R. W. Erickson "Fundamentals of Power
Electronics" (3rd ed.) — see the book's chapters on the averaged switch
model and current-programmed control (Fm/Fg/Fv formulation).

"""

class _LazyControl:
    """Import the (heavy) control package on first attribute access instead
    of at module import time — start-up does not need it until the loop tab
    is used."""
    def __getattr__(self, name):
        import control
        globals()['ct'] = control          # replace the proxy outright
        return getattr(control, name)


ct = _LazyControl()

import numpy as np


DCM_PEAK_NOTE='定频反激 DCM 峰值电流逐周期储能线性化，包含各并联电容 ESR，适用于正负载下每周期都开关、完全退磁的工况。'


def uses_dcm_peak_energy(p, op):
    return (p['topology']=='FLYBACK' and op['mode']=='DCM' and p['control_mode']=='Peak Current Mode'
            and not op.get('outputs') and not op.get('coupled_model') and p.get('feedback_mode','SSR')=='SSR')


def build_loop_models(p, op):
    """One plant factory for GUI, API, reports and corners, using solved op."""
    models, plant = _build_loop_models(p, op)
    from capacitor_impedance import bank_uses_curves
    if any(bank_uses_curves(parameters.get(side + '_capacitors'))
           for parameters in [p, *(p.get('outputs') or [])] for side in ('input', 'output')):
        note = '阻抗曲线用于稳态频谱分流、损耗和纹波后处理；环路沿用原功率级的标称电容参数。'
        plant.model_note = ' '.join(filter(None, (getattr(plant, 'model_note', None), note)))
    return models, plant


def _build_loop_models(p, op):
    if op.get('llc'):
        from llc_model import build_loop as build_llc_loop
        from llc_settings import effective
        return build_llc_loop(effective(p), op['llc'])
    if op.get('cot'):
        from cot_loop import build_loop
        return build_loop(p, op)
    if op.get('niso_model'):
        from nonisolated import build_loop
        return build_loop(p,op)
    if op.get('acf_model',{}).get('converged'):
        from acf_loop import build_loop
        return build_loop(p,op)
    if (p['topology']!='QR-FLYBACK' and op.get('coupled_model')
            and not op['coupled_model'].get('ideal_fallback')):
        from multi_output_loop import build_coupled_loop
        return build_coupled_loop(p, op)
    if p['topology'] == 'QR-FLYBACK' and p['control_mode']=='Peak Current Mode' and p.get('feedback_mode','SSR')=='SSR':
        from qr_loop import plant as qr_plant
        from types import SimpleNamespace
        gvc,detail=qr_plant(p,op)
        gc=make_compensator(p).get_transfer_function()
        from output_capacitors import build_output_filters
        caps = dict(output_capacitors=[dict(C=c, ESR=r) for c, r in detail['capacitors']])
        filt = build_output_filters([caps], [1/detail['output_conductance']], [detail['vcap']])
        gvc._load_plant = _rc_load_plant(filt, detail['d_iout_d_ipk']/detail['sense_gain'])
        gvc._load_response_note = ('QR 周期平均模型。多路时沿用环路的刚性匝比折算负载与电容，'
                                   '仅在所选反馈端口注入电流阶跃。')
        note=('QR/BCM 峰值电流控制的周期平均低频近似：按实际电压、峰值电流及变频线性化；'
              '并联电容分别计入 ESR。Gvc 输入为放大后 CS 等效控制指令；'
              'A_sense 只表示采样增益，不代替真实 COMP 管脚的前馈/电平转换。'
              '损耗按工作点常数比例近似，不含谷底跳变、开关延迟及光耦动态。')
        if detail['multi_output']:
            note=detail['multi_output']['assumptions']+note
        if op.get('qr_coupled_model'):
            note=('直流工作点来自独立QR绕组矩阵/谷底稳态解；以下环路仍为按匝比折算的低频约化，'
                  '未对多路换流或离散跳谷进行完整线性化。'+note)
        return (gvc,gc,gvc*gc),SimpleNamespace(model_note=note,qr_linearization=detail,
            loop_metadata=getattr(gvc,'_loop_metadata',None),mode='BCM')
    source, solved = p, op
    if op.get('aggregate_op'):
        p, op = dict(op['aggregate_params']), op['aggregate_op']
        if solved.get('outputs'):
            # Secondary voltages are constrained by the nominal turns ratios.
            # Refer all stored capacitor energy to the selected feedback rail.
            from capacitor_banks import total
            p['C_out'] = sum(total(r)
                             *(r['V_out']/op['V_out'])**2 for r in solved['outputs'])
    psr = source.get('feedback_mode') == 'PSR-MP6005'
    if psr and solved.get('regulation_region') != 'PWM':
        raise ValueError('MP6005 轻载 PFM：不提供 PWM/SSR Bode 裕度；需时域仿真与实测')
    topo = p['topology']
    if uses_dcm_peak_energy(source,solved):
        # Each fully demagnetised cycle delivers eta*L*Ipk²/2. Linearising
        # Pinj/V - V/R gives incremental conductance 2/R at the port.
        from output_capacitors import build_output_filters
        from types import SimpleNamespace
        filt=build_output_filters([p],[op['R']/2],[op['V_out']])
        sense=p['Rs']*p['A_sense']*(1+p.get('ma_slope',0.)*p['L']/op['V_in'])
        if sense <= 0:
            raise ValueError('定频 DCM 峰值电流环路需要正的有效采样增益')
        z=ct.ss(filt.A,filt.B,filt.C,filt.D)
        current_gain=2*op['I_out']/(op['I_sw_pk']*sense)
        gvc=z*current_gain
        gvc._load_plant = _rc_load_plant(filt, current_gain)
        gvc._load_response_note = DCM_PEAK_NOTE
        gc=make_compensator(p).get_transfer_function()
        return (gvc,gc,gvc*gc),SimpleNamespace(mode='DCM',model_note=DCM_PEAK_NOTE)
    cls = {'BUCK': BuckConverter, 'BOOST': BoostConverter,
           'BUCK-BOOST': BuckBoostConverter, 'FLYBACK': FlybackConverter,
           'QR-FLYBACK': FlybackConverter, 'ACF-FORWARD': ActiveClampForwardConverter}[topo]
    # Freeze the design efficiency at this operating point. The ideal core
    # sees U=Vo/eta, R_eq=R/eta; map its output gain back to the real Vo.
    # This is an engineering approximation, NOT a dynamic loss model.
    if p.get('output_capacitors') is not None:
        from capacitor_banks import total,bank
        p=dict(p);p['C_out']=total(p)
        p['Rc']=sum(c['ESR']*c['C']**2 for c in bank(p))/p['C_out']**2
    args = [p['V_in'], op['V_out_equiv'], op['P_in_est'], op['f_sw'], p['L'],
            p['C_out'], p['Vm']]
    kwargs = dict(Rs=p['Rs'], Rc=p['Rc'], A_sense=p.get('A_sense', 1),
                  ma=p.get('ma_slope', 0))
    if topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
        kwargs.update(N=p['N'], Vf=0.0)
    if topo == 'ACF-FORWARD':
        kwargs['Lm'] = p['Lm_forward']
    plant = cls(*args, **kwargs)
    plant.mode, plant.D_actual = op['mode'], op['D']
    gvc = (plant.get_peak_current_mode_transfer_function()
           if p['control_mode'] == 'Peak Current Mode'
           else plant.get_voltage_mode_transfer_function())
    gvc *= op['eta_guess']
    if psr:
        from mp6005 import design_psr
        from loss_model import magnetics_design
        from isolated_outputs import multi_magnetics
        detail = solved.get('psr')
        if detail is None:
            md = multi_magnetics(solved,source) if solved.get('outputs') else magnetics_design(solved,p)
            detail = design_psr(source,solved,md.get('transformer'))
        s = ct.tf('s')
        gvc *= detail['Hfb']*(1-s*op['Ts']/4)/(1+s*op['Ts']/4)
        gc = Compensator2P2Z(detail['KP'],detail['fz'],detail['fp']).get_transfer_function()
        plant.model_note = detail['note']
        gvc._load_response_unavailable = 'PSR 补偿环路使用辅助绕组反推值，当前模型缺少实际输出端口的负载动态。'
    else:
        gc = make_compensator(p).get_transfer_function()
        if topo == 'QR-FLYBACK':
            gvc._load_response_unavailable = '准谐振负载响应需要峰值电流 SSR 的周期平均模型。'
        else:
            gvc._load_plant, gvc._load_response_note = _legacy_load_plant(
                plant, p['control_mode'] == 'Peak Current Mode', op['eta_guess'])
            if solved.get('outputs'):
                gvc._load_response_note += ' 多路沿用 Bode 的刚性匝比约化，仅扰动选中反馈端口。'
    if solved.get('outputs'):
        from multi_output_loop import attach_nominal_context
        attach_nominal_context(gvc, source, solved)
    return (gvc, gc, gvc * gc), plant



def _rc_load_plant(filters, current_gain):
    """Two inputs: commanded injection current and additional sinking load."""
    gains = np.array([[current_gain, -1.]])
    return ct.ss(filters.A, filters.B @ gains, filters.C, filters.D @ gains)


def _legacy_load_plant(plant, peak_mode, eta):
    """State realization of the legacy averaged plant with a real load port.

    i is the averaged inductor current (primary for flyback), v the
    positive equivalent capacitor-terminal voltage, and d the duty change.
    The power-stage equations, prior to peak-control substitution, are
    L·di/dt = a_d·d - k·v and i_injected = k·i + b_d·d.
    """
    from output_capacitors import build_output_filters

    buck = isinstance(plant, BuckConverter)
    boost = isinstance(plant, BoostConverter)
    flyback = isinstance(plant, FlybackConverter)
    forward = isinstance(plant, ActiveClampForwardConverter)
    mode = getattr(plant, 'mode', 'CCM')
    dcm = mode in ('DCM', 'BCM') and not (forward and not peak_mode and mode == 'BCM')
    esr = plant.Rc if forward and not peak_mode and not dcm else 0.
    cap = dict(output_capacitors=[dict(C=plant.C_out, ESR=esr)])
    if dcm:
        kind = 'buck' if buck else 'boost' if boost else 'buckboost'
        ratio = plant.V_out / max(plant.V_in, 1e-9)
        gain, conductance = _dcm_coefficients(plant.V_out, plant.D_actual, ratio, plant.R, kind)
        conductance = max(conductance, 1e-9 * plant.C_out)
        filt = build_output_filters([cap], [1/conductance], [plant.V_out])
        response = _rc_load_plant(filt, gain*conductance/plant.Vm)
        note = ('定频 DCM/BCM 单极点平均模型，沿用 Bode 的标称电容与调制近似。'
                '整个阶跃保持该局部导通模式。')
        return eta * response, note
    if boost and peak_mode:
        return _legacy_peak_boost_load_plant(plant, eta)

    turns = plant.N if flyback else 1.
    k = 1. if buck else turns*plant.D_prime
    a_d = plant.V_out if boost else turns*plant.V_out/plant.D
    b_d = 0. if buck else -plant.V_out/(plant.D_prime*plant.R)
    if peak_mode:
        fm = plant.Fm
        fi = plant.Rs*plant.A_sense
        if flyback:
            fv = -plant.D_prime**2 * plant.Ts * fi / (2*plant.L)
        elif isinstance(plant, BuckBoostConverter):
            fv = -plant.Fv  # magnitude convention for the negative output
        else:
            fv = plant.Fv
    else:
        fm, fi, fv = 1/plant.Vm, 0., 0.

    # Substitute d = Fm*(command - Fi*i - Fv*v) in both plant equations.
    # The extra load current is subtracted after average rectifier injection.
    filt = build_output_filters([cap], [plant.R], [plant.V_out])
    injection_state = np.r_[k-b_d*fm*fi, np.zeros(len(filt.A))]
    injection_input = np.array([b_d*fm, -1.])
    injection_voltage = -b_d*fm*fv
    feed = filt.D[0, 0]
    load_node_factor = 1-feed*injection_voltage
    voltage_state = (np.r_[0., filt.C[0]]+feed*injection_state)/load_node_factor
    voltage_input = feed*injection_input/load_node_factor
    inductor_state = -(k+a_d*fm*fv)*voltage_state
    inductor_state[0] -= a_d*fm*fi
    inductor_input = np.array([a_d*fm, 0.])-(k+a_d*fm*fv)*voltage_input
    filter_state = np.column_stack((np.zeros(len(filt.A)), filt.A))
    filter_state += np.outer(filt.B[:, 0], injection_state+injection_voltage*voltage_state)
    filter_input = np.outer(filt.B[:, 0], injection_input+injection_voltage*voltage_input)
    response = ct.ss(np.vstack((inductor_state/plant.L, filter_state)),
                     np.vstack((inductor_input/plant.L, filter_input)),
                     eta*voltage_state[None, :], eta*voltage_input[None, :])
    note = ('定频 CCM 平均模型，沿用环路的预设效率与输出电容。'
            + ('保留等效 ESR。' if esr else '当前 Bode 模型采用理想电容，阶跃未计 ESR 瞬时压降。'))
    if isinstance(plant, BuckBoostConverter):
        note += ' 反相输出按电压幅值闭环。'
    return response, note


def _legacy_peak_boost_load_plant(plant, eta):
    """Use the retained peak-Boost damping model for both input channels.

    The published legacy Bode code approximates the current-feedback damping.
    Use its same second-order poles and the averaged load-port numerator
    Ls + Vo*Fm*Fi, from the inductor equation at fixed current command.
    """
    omega, q_factor, command_gain = plant._peak_current_parameters()
    k = plant.D_prime
    current_gain = plant.Fm*plant.V_out
    direct_command = command_gain*eta*omega**2
    inverse_rhp_zero = plant.L/(k*k*plant.R)
    load_gain = direct_command/(k*current_gain)
    # Observable realization has one common denominator and independent
    # numerator coefficients for the command and sinking-current inputs.
    response = ct.ss([[-omega/q_factor, 1.], [-omega**2, 0.]],
                     [[-direct_command*inverse_rhp_zero, -load_gain*plant.L],
                      [direct_command, -load_gain*current_gain*plant.Rs*plant.A_sense]],
                     [[1., 0.]], [[0., 0.]])
    note = ('定频峰值电流 Boost 的 CCM 平均模型，沿用当前 Bode 阻尼近似与标称电容。'
            '阶跃未计 ESR 瞬时压降。')
    return response, note


def _dcm_coefficients(V_out, D, M, R, kind):
    """Duty-to-voltage DC gain and total output incremental conductance."""
    if kind == 'buck':
        return 2*V_out/D*(1-M)/(2-M), (2-M)/((1-M)*R)
    if kind == 'boost':
        return 2*V_out/D*(M-1)/(2*M-1), (2*M-1)/((M-1)*R)
    return V_out/D, 2/R


def _dcm_gvd(s, V_out, D, M, R, C, kind):
    """DCM control-to-output Gvd(s): single-pole, no RHP zero.

    Erickson, Fundamentals of Power Electronics, 3rd ed., Table 15.3
    (approximate DCM model of Fig. 15.20).  The exact DCM model retains a
    second pole and an RHP zero, but both occur near / above the switching
    frequency and are ignored for loop analysis.  'kind' in
    {'buck', 'boost', 'buckboost'} (flyback uses the buck-boost form).
    """
    Gd0, conductance = _dcm_coefficients(V_out, D, M, R, kind)
    wp = conductance / C
    return Gd0 / (1.0 + s / max(wp, 1e-9))


def normalize_controller_type(value):
    kind = str(value).strip().lower()
    if kind == 'pi':
        return 'auto'  # compatibility with configs from the withdrawn PI update
    if kind not in ('auto', 'type2', 'type3'):
        raise ValueError('Controller type must be auto / type2 / type3')
    return kind


def resolve_controller_type(selection='auto', control_mode='Voltage Mode'):
    kind = normalize_controller_type(selection)
    return ('type2' if control_mode == 'Peak Current Mode' else 'type3') if kind == 'auto' else kind


def make_compensator(p):
    """Shared GUI/API factory. Control mode selects the plant, not an explicit controller."""
    kind = resolve_controller_type(p.get('controller_type', 'auto'), p.get('control_mode'))
    if kind == 'type2':
        return Compensator2P2Z(p['KP'], p['fz1'], p['fp1'])
    return Compensator3P3Z(p['KP'], p['fz1'], p['fz2'], p['fp1'], p['fp2'])


class Compensator3P3Z:
    """Type III: three poles (including the origin), two finite zeros."""

    def __init__(self, KP, fz1, fz2, fp1, fp2):
        self.s = ct.tf('s')
        self.KP = KP
        self.wz1 = 2 * np.pi * fz1
        self.wz2 = 2 * np.pi * fz2
        self.wp1 = 2 * np.pi * fp1
        self.wp2 = 2 * np.pi * fp2

    def get_transfer_function(self):
        Gc = (self.KP * (1 + self.s / self.wz1) * (1 + self.s / self.wz2)
              / self.s / (1 + self.s / self.wp1) / (1 + self.s / self.wp2))
        return Gc


class Compensator2P2Z:
    """Type II: two poles (including the origin), one finite zero."""

    def __init__(self, KP, fz, fp):
        self.s = ct.tf('s')
        self.KP = KP
        self.wz = 2 * np.pi * fz
        self.wp = 2 * np.pi * fp

    def get_transfer_function(self):
        Gc = self.KP * (1 + self.s / self.wz) / self.s / (1 + self.s / self.wp)
        return Gc


def _pwm_fm(f_switch, Rs, A_sense, ma, M1, M2):
    """PWM modulator gain (Ridley/Basso): Fm = 1/((ma+(M1-M2)/2)*Ts*Rs),
    scaled by the sense amplifier gain.  Falls back to the mean of the up/down
    slopes when the raw denominator is not positive (e.g. no slope comp with
    D > 0.5) so Fm stays finite and positive."""
    den = ma + (M1 - M2) / 2.0
    if den <= 0:
        den = (M1 + M2) / 2.0
    return f_switch / (Rs * A_sense * max(abs(den), 1.0))


class BuckConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm,
                 Rs=0.01, Rc=15e-3, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.Rs = Rs
        self.Rc = Rc
        self.A_sense = A_sense          # current-sense amplifier gain
        self.ma = ma                    # slope compensation (A/s)
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = V_out / V_in if V_in > 0 else 0.5
        self.Ts = 1 / f_switch

        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma, V_in / L, V_out / L)

        self.Fg = (self.D ** 2 * self.Ts * Rs * A_sense) / (2 * L)
        self.Fv = ((1 - 2 * self.D) * self.Ts * Rs * A_sense) / (2 * L)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buck') / self.Vm
        den = 1 + self.s * self.L / self.R + self.s ** 2 * self.L * self.C_out
        Gvd = self.V_out / self.D / den
        Gvc = Gvd / self.Vm
        return Gvc

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buck') / self.Vm
        Fi = self.Rs * self.A_sense
        term1 = self.Fm * self.V_out * Fi / (self.D * self.R)
        term2 = (self.Fm * self.Fv * self.V_out) / self.D

        omega_c = 1 / np.sqrt(self.L * self.C_out) * np.sqrt(1 + term1 + term2)
        Q_c = (self.R * np.sqrt(self.C_out / self.L)
               * np.sqrt(1 + term1 + term2)
               / (1 + self.R * self.C_out * self.Fm * self.V_out * Fi
                  / (self.D * self.L)))

        G_c0 = self.V_out * self.Fm / self.D / (1 + term1 + term2)

        num = G_c0
        den = 1 + self.s / (Q_c * omega_c) + (self.s / omega_c) ** 2

        Gvc = num / den
        return Gvc


class ActiveClampForwardConverter(BuckConverter):
    """Buck-derived forward plant below the clamp resonance (TI SLUA535A).

    Primary current sensing observes iL/N plus magnetizing current, so Rs/N
    is used on the secondary-referred model. The magnetizing ON slope is
    included in the equivalent artificial current ramp. Clamp resonance and
    sampled-data/dead-time effects require a switching model; the UI reports
    a crossover ceiling instead of claiming broadband model accuracy.
    """
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm, N,
                 Rs=.01, Rc=.015, A_sense=1.0, ma=0.0, Lm=220e-6, Vf=.7):
        if N <= 0 or Lm <= 0:
            raise ValueError('Forward: N and Lm must be positive')
        self.turns_ratio = N
        super().__init__(V_in/N, V_out, P_out, f_switch, L, C_out, Vm,
                         Rs/N, Rc, A_sense=A_sense,
                         ma=N*(ma+V_in/Lm))
        self.D = (V_out+Vf)/(V_in/N)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') == 'DCM':
            return super().get_voltage_mode_transfer_function()
        s = self.s
        den = 1+s*(self.L/self.R+self.Rc*self.C_out) + \
              s**2*self.L*self.C_out*(1+self.Rc/self.R)
        return self.V_in*(1+s*self.Rc*self.C_out)/(self.Vm*den)


class BoostConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm,
                 Rs=0.01, Rc=15e-3, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.Rs = Rs
        self.Rc = Rc
        self.A_sense = A_sense
        self.ma = ma
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = 1 - V_in / V_out if V_out > 0 else 0.5
        self.D_prime = 1 - self.D
        self.Ts = 1 / f_switch

        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma,
                          V_in / L, (V_out - V_in) / L)

        self.Fg = ((2 * self.D - 1) * self.Ts * Rs * A_sense) / (2 * L)
        self.Fv = (self.D_prime ** 2 * self.Ts * Rs * A_sense) / (2 * L)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'boost') / self.Vm
        den = (1 + self.s * self.L / (self.D_prime ** 2 * self.R)
               + self.s ** 2 * self.L * self.C_out / (self.D_prime ** 2))
        Gvd = (self.V_out / self.D_prime
               * (1 - self.s * self.L / (self.D_prime ** 2 * self.R)) / den)
        Gvc = Gvd / self.Vm
        return Gvc

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'boost') / self.Vm
        omega_c, Q_c, G_c0 = self._peak_current_parameters()
        num = G_c0 * (1 - self.s * self.L / (self.D_prime ** 2 * self.R))
        den = 1 + self.s / (Q_c * omega_c) + (self.s / omega_c) ** 2
        return num / den

    def _peak_current_parameters(self):
        Fi = self.Rs * self.A_sense
        term1 = 2 * self.Fm * self.V_out * Fi / (self.D_prime ** 2 * self.R)
        term2 = (self.Fm * self.Fv * self.V_out) / self.D_prime

        omega_c = (self.D_prime / np.sqrt(self.L * self.C_out)
                   * np.sqrt(1 + term1 + term2))
        Q_c = (self.D_prime * self.R * np.sqrt(self.C_out / self.L)
               * np.sqrt(1 + term1 + term2)
               / (1 + self.R * self.C_out * self.Fm * self.V_out * Fi
                  / (self.D_prime * self.L)
                  - self.Fm * self.Fv * self.V_out / self.D_prime))

        G_c0 = self.V_out * self.Fm / self.D_prime / (1 + term1 + term2)
        return omega_c, Q_c, G_c0


class BuckBoostConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm,
                 Rs=0.01, Rc=15e-3, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.Rs = Rs
        self.Rc = Rc
        self.A_sense = A_sense
        self.ma = ma
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = V_out / (V_in + V_out) if (V_in + V_out) > 0 else 0.5
        self.D_prime = 1 - self.D
        self.Ts = 1 / f_switch

        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma, V_in / L, V_out / L)

        self.Fg = (self.D ** 2 * self.Ts * Rs * A_sense) / (2 * L)
        self.Fv = -(self.D_prime ** 2 * self.Ts * Rs * A_sense) / (2 * L)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        den = (1 + self.s * self.L / (self.D_prime ** 2 * self.R)
               + self.s ** 2 * self.L * self.C_out / (self.D_prime ** 2))
        Gvd = (-self.V_out / self.D_prime / self.D
               * (1 - self.s * self.D * self.L / (self.D_prime ** 2 * self.R))
               / den)
        Gvc = Gvd / self.Vm
        return Gvc

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        Fi = self.Rs * self.A_sense
        term1 = (self.Fm * self.V_out * (1 + self.D) * Fi
                 / (self.D_prime ** 2 * self.R * self.D))
        term2 = -(self.Fm * self.Fv * self.V_out) / self.D_prime / self.D

        omega_c = (self.D_prime / np.sqrt(self.L * self.C_out)
                   * np.sqrt(1 + term1 + term2))
        Q_c = (self.D_prime * self.R * np.sqrt(self.C_out / self.L)
               * np.sqrt(1 + term1 + term2)
               / (1 + self.R * self.C_out * self.Fm * self.V_out * Fi
                  / (self.D * self.L)
                  + self.Fm * self.Fv * self.V_out / self.D_prime))

        G_c0 = (-self.V_out * self.Fm / self.D_prime / self.D
                / (1 + term1 + term2))

        num = G_c0 * (1 - self.s * self.D * self.L / (self.D_prime ** 2 * self.R))
        den = 1 + self.s / (Q_c * omega_c) + (self.s / omega_c) ** 2

        Gvc = num / den
        return Gvc


class FlybackConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm, N=10,
                 Rs=0.01, Rc=15e-3, Vf=0.7, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.N = N
        self.Rs = Rs
        self.Rc = Rc
        self.Vf = Vf
        self.A_sense = A_sense          # current-sense amplifier gain
        self.ma = ma                    # slope compensation (A/s, primary)
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = (N * (V_out + Vf) / (V_in + N * (V_out + Vf))
                  if (V_in + N * (V_out + Vf)) > 0 else 0.5)
        self.D_prime = 1 - self.D
        self.Ts = 1 / f_switch

        # PWM modulator gain (Ridley/Basso): Fm = 1/((ma + (M1-M2)/2)·Ts·Rs),
        # scaled by the sense amplifier gain.  With no slope compensation and
        # D > 0.5 the raw denominator goes negative -> fall back to the mean
        # of the up/down slopes (finite, positive).
        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma, V_in / L,
                          (V_out + Vf) * N / L)
        self.fm_fallback = ma + ((V_out + Vf) * N - V_in) / L / 2.0 <= 0

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        delta = (1 + self.s * self.L / (self.N * self.D_prime) ** 2 / self.R
                 + self.s ** 2 * self.L * self.C_out
                 / (self.N * self.D_prime) ** 2)
        Gvd = (self.V_out / self.D / self.D_prime
               * (1 - self.s * self.D * self.L
                  / (self.N * self.D_prime) ** 2 / self.R) / delta)
        return Gvd / self.Vm

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        delta = (1 + self.s * self.L / (self.N * self.D_prime) ** 2 / self.R
                 + self.s ** 2 * self.L * self.C_out
                 / (self.N * self.D_prime) ** 2)
        Gvd = (self.V_out / self.D / self.D_prime
               * (1 - self.s * self.D * self.L
                  / (self.N * self.D_prime) ** 2 / self.R) / delta)

        Fg = (self.D ** 2 * self.Ts * self.Rs * self.A_sense) / (2 * self.L)
        Fv = -(self.D_prime ** 2 * self.Ts * self.Rs * self.A_sense) \
            / (2 * self.L)

        Gid = (self.N * self.V_out * (1 + self.D)
               * (1 + self.s * self.R * self.C_out / (1 + self.D))
               / self.D / (self.N * self.D_prime) ** 2 / self.R / delta)

        # Current-loop return: the sensed inductor current enters the PWM
        # comparator through Fi = Rs*A_sense (the factor the model used to
        # miss -> Rs barely changed the loop).  Gid is duty->inductor current
        # [A/duty], so Fi*Gid is comparator-referred [V/duty].
        Fi = self.Rs * self.A_sense
        Gvc = self.Fm * Gvd / (1 + self.Fm * (Fi * Gid + Fv * Gvd))
        return Gvc
