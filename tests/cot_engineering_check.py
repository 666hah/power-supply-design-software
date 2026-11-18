"""Independent physical invariants for phase mismatch and dynamic COT review."""
from pathlib import Path
import sys
import unittest
import copy
import math
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.specification import load_spec
from loss_model import compute_design
from cot_loop import build_loop, transient_response
from cot_settings import configuration


def spec(**extra):
    return load_spec(dict(topology='BUCK',control_mode='Constant On-Time',buck_phases=4,
        V_in=12.,V_out=3.,P_out=48.,f_sw=300e3,L=10e-6,Rds_on=.015,Rds_aux=.010,
        Rs=.002,inductor_design_enabled=False,inductor_dcr=.006,d_in_enable=False,d_out_enable=False)|extra)


class CotEngineering(unittest.TestCase):
    def test_unequal_resistors_conserve_volt_seconds_and_current(self):
        p=spec(cot_config=dict(phase_parameters=[{'dcr_scale':2.},{},{},{}]))
        result=compute_design(p); op=result['op']; rows=op['cot']['phase_data']
        self.assertAlmostEqual(sum(r['current_avg_A'] for r in rows),16.,places=9)
        self.assertLess(rows[0]['current_avg_A'],rows[1]['current_avg_A'])
        for r in rows:
            v=r['duty']*(12-r['current_avg_A']*(r['rhigh_ohm']+r['rs_ohm']-r['rlow_ohm']))
            self.assertAlmostEqual(v,3+r['current_avg_A']*(r['rlow_ohm']+r['dcr_ohm']),places=8)
        self.assertAlmostEqual(result['P_sense'],sum(r['rs_ohm']*r['high_rms_A']**2 for r in rows))
        self.assertAlmostEqual(result['P_mag'],sum(r['P_total'] for r in result['mag']['phase_inductors']))
        self.assertAlmostEqual(result['P_semi'],sum(r['P_total'] for r in result['semi']['phases']))

    def test_finite_balance_reduces_current_error_but_sensor_offset_remains(self):
        cfg=dict(phase_parameters=[{'dcr_scale':2.},{},{},{}])
        a=compute_design(spec(cot_config=cfg))['op']['cot']
        b=compute_design(spec(cot_config=cfg|dict(balance_gain_v_per_a=.2)))['op']['cot']
        self.assertLess(b['engineering']['phase_imbalance_pct'],a['engineering']['phase_imbalance_pct']/5)
        wrong=copy.deepcopy(cfg);wrong['phase_parameters'][0]['sense_offset_A']=1.
        c=compute_design(spec(cot_config=wrong|dict(balance_gain_v_per_a=2.)))['op']['cot']
        self.assertGreater(c['phase_data'][1]['current_avg_A']-c['phase_data'][0]['current_avg_A'],.9)

    def test_mismatch_residual_ripple_and_nonzero_dynamic_cap(self):
        cfg=dict(phase_parameters=[{'L_scale':.8},{},{},{}],dynamic=dict(step_A=4.,delay_s=5e-6,droop_V=.1,overshoot_V=.1))
        result=compute_design(spec(Rds_on=0,Rds_aux=0,Rs=0,inductor_dcr=0,cot_config=cfg))
        cot=result['op']['cot'];dyn=cot['engineering']['dynamic']
        self.assertGreater(cot['total_output_current_ripple_A'],0)
        self.assertGreater(dyn['required_droop_F'],0)
        self.assertAlmostEqual(cot['total_output_current_ripple_A'],np.ptp(result['wf']['iL_total']),places=6)

    def test_matched_full_state_model_matches_common_mode(self):
        base=spec(cot_config={}); op=compute_design(base)['op'];old=build_loop(base,op)[0][0]
        # Activate sharing with perfectly matched sensors. It must leave the
        # common-mode response untouched while damping differential currents.
        p=spec(cot_config={'balance_gain_v_per_a':.2}); op=compute_design(p)['op'];new=build_loop(p,op)[0][0]
        frequencies=2j*np.pi*np.array([10.,100.,1000.,10000.])
        np.testing.assert_allclose(new(frequencies),old(frequencies),rtol=1e-9)
        np.testing.assert_allclose(new._load_disturbance(frequencies),
                                   old._load_disturbance(frequencies),rtol=1e-9)

    def test_total_current_feedback_reduces_dc_control_gain(self):
        p=spec();op=compute_design(p)['op'];base=build_loop(p,op)[0][0]
        p=spec(cot_config=dict(model='current_feedback',current_feedback_hz_per_a=5000.))
        op=compute_design(p)['op'];current=build_loop(p,op)[0][0]
        expected=float(base(0).real)/(1+5000*float(base(0).real)/op['R'])
        self.assertAlmostEqual(float(current(0).real),expected,places=12)

    def test_signed_dc_load_impedance_with_total_current_feedback(self):
        gain = 5000.
        p = spec(cot_config=dict(model='current_feedback', current_feedback_hz_per_a=gain,
                                 load_mode='current'))
        op = compute_design(p)['op']
        plant = build_loop(p, op)[0][0]
        phase = op['cot']['phase_data'][0]
        high = phase['rhigh_ohm'] + phase['rs_ohm']
        low = phase['rlow_ohm']
        duty = phase['duty']
        phase_resistance = duty * high + (1-duty) * low + phase['dcr_ohm']
        duty_gain = op['cot']['bus_voltage_V'] - (high-low) * phase['current_avg_A']
        output_resistance = phase_resistance/op['cot']['phases'] + gain*duty_gain*phase['ton_s']
        self.assertAlmostEqual(float(plant._load_disturbance(0).real), -output_resistance, places=12)

    def test_limit_uses_measured_current_and_delay(self):
        cfg=dict(phase_limit_A=6.,limit_delay_s=100e-9,phase_parameters=[dict(sense_gain=1.1,sense_offset_A=.2),{},{},{}])
        op=compute_design(spec(cot_config=cfg))['op'];row=op['cot']['engineering']['protection'][0]
        self.assertAlmostEqual(row['effective_trip_A'],(6-.2)/1.1)
        self.assertGreater(row['delayed_trip_peak_A'],row['effective_trip_A'])

    def test_explicit_phase_count_is_not_silently_replaced(self):
        with self.assertRaises(ValueError):spec(cot_config=dict(phase_parameters=[{}]))
        p=spec();before=copy.deepcopy(p);configuration(p);self.assertEqual(p,before)

    def test_independent_tolerance_fields_and_negative_sensor_offset(self):
        from tolerance_analysis import available_variables,_variables,_materialize
        p=spec();variables=available_variables(p);names={r['path'] for r in variables}
        self.assertIn('L',names);self.assertIn('cot_config.phase_parameters.3.L_scale',names)
        row=dict(path='cot_config.phase_parameters.0.sense_offset_A',low=-.1,high=.1,distribution='uniform')
        self.assertEqual(_variables(p,[row])[0]['low'],-.1)
        self.assertEqual(len(_materialize(p)['cot_config']['phase_parameters']),4)

    def test_per_phase_monte_carlo_produces_current_sharing_distribution(self):
        from tolerance_analysis import analyze
        p=spec(V_in_min=12.,V_in_max=12.,cot_config=dict(balance_gain_v_per_a=.05))
        variables=[dict(path=f'cot_config.phase_parameters.{i}.dcr_scale',low=.8,high=1.2,distribution='uniform') for i in (0,1)]
        result=analyze(p,variables,samples=8,seed=4,load_fracs=(1.,),max_evaluations=30)
        self.assertEqual(result['failure_count'],0)
        row=next(r for r in result['rows'] if r['id']=='cot_imbalance')
        self.assertGreater(row['worst'],0)
        self.assertIsNotNone(row['statistics'])

    def test_closed_loop_transient_and_impedance_have_defined_units(self):
        p=spec(cot_config=dict(dynamic=dict(step_A=1.,droop_V=.1,overshoot_V=.1)))
        op=compute_design(p)['op'];r=transient_response(p,op)
        self.assertTrue(r['available']);self.assertTrue(r['settled'])
        self.assertGreater(r['droop_V'],0.)
        self.assertEqual(len(r['zout_magnitude_ohm']),len(r['zout_frequency_Hz']))
        self.assertAlmostEqual(r['voltage_delta_V'][-1],0.,delta=.001)

    def test_source_drop_and_dead_time_preserve_physical_dc_budget(self):
        p=spec(cot_config=dict(source_resistance_ohm=.05,dead_time_s=30e-9,body_diode_V=.7))
        r=compute_design(p);op=r['op'];cot=op['cot']
        self.assertAlmostEqual(op['V_in_bus'],12-.05*op['I_in_avg'],places=8)
        self.assertAlmostEqual(cot['base_ton_s'],3/(op['V_in_bus']*p['f_sw']),places=14)
        self.assertAlmostEqual(r['P_source'],.05*op['I_in_avg']**2)
        self.assertGreater(r['semi']['phases'][0]['auxiliary']['P_body'],0)
        for phase in cot['phase_data']:
            self.assertAlmostEqual(phase['rise_voltage_V']*phase['ton_s'],
                                   phase['fall_voltage_V']*phase['toff_s'],places=13)

    def test_freezing_a_mismatched_phase_does_not_apply_multiplier_twice(self):
        from analysis_workflows import pin_hardware
        p=spec(cot_config=dict(phase_parameters=[dict(L_scale=.9,dcr_scale=.8),{},{},{}]))
        result=compute_design(p); fixed=pin_hardware(p,result); second=compute_design(fixed)
        self.assertEqual(fixed['_fixed_inductor']['inductor_dcr'],p['inductor_dcr'])
        for a,b in zip(result['op']['cot']['phase_data'],second['op']['cot']['phase_data']):
            self.assertAlmostEqual(a['dcr_ohm'],b['dcr_ohm'],places=14)
            self.assertAlmostEqual(a['current_avg_A'],b['current_avg_A'],places=12)


if __name__=='__main__':unittest.main(verbosity=2)
