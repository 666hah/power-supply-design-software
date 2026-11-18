"""Reproduce the four-phase engineering example from cited component data."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'examples/96W_BUCK_COT_4PH.json'


def build():
    p=json.loads(PATH.read_text('utf-8'))
    p.update(L=.30e-6,inductor_dcr=.00175,inductor_rated_current=27.6,
             inductor_saturation_current=41.,inductor_extra_loss=.15,
             Rds_on=.0053,Rds_aux=.0024,Qg=13e-9,Qg_aux=25e-9,Coss=208e-12,Coss_aux=389e-12,
             Vgs=4.5,Vth=1.4,Vgp_on=2.8,Vgp_off=2.8,Qg_th=2.5e-9,Qgs=5.1e-9,Qgd=2.8e-9,
             gfs=76.,mos_miller_mode='gfs',mos_charge_mode='manual',
             fc_target=20000.,pm_target=80.,cot_kp_hz=2450332.0777366706,cot_ki_hz_per_s=9.367015802142029e10,
             input_capacitors=[dict(C=330e-6,ESR=.014,ESL=2e-9) for _ in range(4)],
             output_capacitors=[dict(C=330e-6,ESR=.009,ESL=2e-9) for _ in range(16)])
    phases=[dict(L_scale=l,dcr_scale=r,rhigh_scale=1.,rlow_scale=1.,ton_scale=1.,sense_gain=g,sense_offset_A=o)
            for l,r,g,o in zip([.95,1.05,1.,1.],[.95,1.05,1.02,.98],[1.005,.995,1.01,.99],[.1,-.1,.05,-.05])]
    p['cot_config']=dict(model='current_feedback',controller_reference='ti_dcap_plus',
        current_feedback_hz_per_a=4000.,current_filter_hz=30000.,
        balance_gain_v_per_a=.02,balance_bandwidth_hz=2000.,balance_max_duty=.05,
        phase_limit_A=32.,limit_delay_s=20e-9,fault_mode='hiccup',fault_delay_s=.0002,hiccup_s=.002,
        uvlo_on_V=8.,uvlo_off_V=7.5,ovp_V=1.38,dead_time_s=20e-9,body_diode_V=.8,body_qrr_C=14.7e-9,
        light_load='forced',source_resistance_ohm=.01,source_inductance_H=100e-9,source_rise_s=.001,
        prebias_V=0.,shutdown_s=.007,load_mode='current',load_rise_s=1e-6,
        phase_imbalance_limit_pct=10.,phase_parameters=phases,
        dynamic=dict(step_A=40.,rise_s=1e-6,delay_s=1e-6,droop_V=.06,overshoot_V=.06),
        acceptance=dict(pm_min_deg=45.,gm_min_db=6.,overshoot_pct=5.,undershoot_pct=5.,
                        recovery_s=.001,settling_band_pct=2.,imbalance_pct=10.,input_peak_A=20.))
    p['spice_config']=dict(enable_delay_ms=2.,soft_start_ms=2.,step_ms=5.,stop_ms=8.,load_after=.5,
                           include_cap_esl=0.,simulation_threads=4.,fra_enabled=0.,simulation_timeout_s=180.,
                           fra_start_hz=2000.,fra_stop_hz=40000.)
    def item(maker,model,conditions,**ratings):
        return dict(manufacturer=maker,model=model,conditions=conditions,**ratings)
    items={
        'U_CTRL':item('Texas Instruments','TPS536C7B1 · D-CAP+ 结构参考',
                      'SLUSDI9 §7.6；本例为公开结构的频率域行为实现；增益与保护阈值为本项目配置，未对应芯片寄存器。'),
        'Q1':item('Texas Instruments','CSD17577Q3A',
                  '每相高侧。SLPS515A §5.1：25°C，Rds 5.3mΩ@4.5V/10A；Qg 13nC、Coss 208pF@15V；采用电气表值。',voltage_V=30.),
        'Q2':item('Texas Instruments','CSD17576Q5B',
                  '每相低侧。SLPS497A §5.1：25°C，Rds 2.4mΩ@4.5V/25A；Qg25nC、Coss389pF@15V；Qrr14.7nC@15V25A300A/µs。',voltage_V=30.),
        'L1':item('Coilcraft','XAL7030-301MEC',
                  '每相。Document863-1：0.30µH±20%，DCR典型1.75mΩ/最大1.92mΩ；Isat41A对应L下降30%；Irms27.6A对应40K温升。'),
    }
    for i in range(4):
        items[f'C_IN{i+1}']=item('Panasonic','25SVPF330M','330µF±20%，100kHz ESR上限14mΩ，纹波5A；ESL2nH为项目几何假设。',
                                 capacitor_type='other',voltage_V=25.,ripple_A=5.)
    # Native registry uses A/B followed by C... for the output bank.
    from sys import path
    path.insert(0,str(ROOT))
    from capacitor_banks import output_ref
    for i in range(16):
        items[output_ref(1,i+1)]=item('Panasonic','2R5TPE330M9','330µF±20%，100kHz ESR上限9mΩ，纹波3.9A；ESL2nH为项目几何假设。',
                                         capacitor_type='other',voltage_V=2.5,ripple_A=3.9)
    p['component_management']=dict(version=1,zone='I',items=items,
        overrides=dict(other_voltage=.8,other_ripple=.8),override_reason='本工程聚合物电容电压和纹波采用0.8初选余量，非原厂统一降额标准。')
    p['__example_note']='四相1.2V/80A工程参考。真实离散器件参数与TI D-CAP+公开控制结构分别引用；不等同TPS536C7原厂参考电路。'
    p['__cot_sources']={
        'controller':'https://www.ti.com/lit/ds/symlink/tps536c7.pdf',
        'high_mos':'https://www.ti.com/lit/ds/symlink/csd17577q3a.pdf',
        'low_mos':'https://www.ti.com/lit/ds/symlink/csd17576q5b.pdf',
        'inductor':'https://www.coilcraft.com/getmedia/0d05a05e-d55d-4a0c-911d-46bd73686633/xal7030.pdf',
        'input_cap':'https://na.industrial.panasonic.com/products/capacitors/polymer-capacitors/series/91057/model/91095',
        'output_cap':'https://util01.industrial.panasonic.com/ww/utilities/ds/chr-vw/2R5TPE330M9',
        'assumptions':'每颗ESL2nH、电感附加损耗0.15W、源R/L、采样误差、死区及所有控制增益/保护/验收阈值为工程配置；Coss按15V单点，未拟合非线性曲线。'}
    PATH.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':build()
